import json
import os
import subprocess
import sys
import tempfile
import threading
import time

from pydantic import ValidationError

from shared.job_contract import AnnotationJobRequest
from shared.job_progress import JobProgressEvent

_SUBPROCESS_ENV_KEYS = (
    "OLLAMA_ROUTER_URL",
    "AUTOANNOTATION_MODEL_MODE",
    "AUTOANNOTATION_OLLAMA_KEEP_ALIVE",
    "WORKER_CACHE_DIR",
    "WORKER_OUTPUT_DIR",
)

# Cap on how much non-progress stderr we keep in memory for failure
# diagnostics. This is a tail buffer, not a log sink; annotation logs are
# never dumped to the live terminal by default (see WORKER_JOB_CAPTURE_STDERR).
_STDERR_LOG_TAIL_LIMIT_CHARS = 8000

_active_lock = threading.Lock()
_active_processes: dict[str, subprocess.Popen] = {}


def _load_annotation_main():
    from autoannotation import __main__ as annotation_cli

    return annotation_cli.main


def _register_job_process(job_id: str | None, proc: subprocess.Popen) -> None:
    if not job_id:
        return
    with _active_lock:
        _active_processes[job_id] = proc


def _unregister_job_process(job_id: str | None, proc: subprocess.Popen) -> None:
    if not job_id:
        return
    with _active_lock:
        if _active_processes.get(job_id) is proc:
            _active_processes.pop(job_id, None)


def terminate_active_jobs() -> None:
    """Send SIGTERM to in-flight annotation subprocesses (bench Ctrl+C)."""
    with _active_lock:
        procs = list(_active_processes.values())
    for proc in procs:
        try:
            proc.terminate()
        except (ProcessLookupError, OSError):
            pass
    for proc in procs:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except (ProcessLookupError, OSError):
                pass
        except (ProcessLookupError, OSError):
            pass


def _run_inprocess(request: AnnotationJobRequest, annotation_main=None, progress_cb=None):
    main = annotation_main or _load_annotation_main()
    # Override paths from worker env, ignoring coordinator-sent paths for security.
    cache_dir = os.getenv("WORKER_CACHE_DIR", "./.cache")
    output_dir = os.getenv("WORKER_OUTPUT_DIR", "gen_json")
    return main(
        gene=None,
        progress_cb=progress_cb,
        profile=request.profile,
        profile_config=request.profile_config,
        organism=request.organism,
        strain=request.strain,
        locus=request.locus,
        name=request.name,
        cache_dir=cache_dir,
        output_dir=output_dir,
        gene_name_cache=request.gene_name_cache,
        no_online_name_lookup=not request.allow_online_name_lookup,
        refresh_gene_name_cache=request.refresh_gene_name_cache,
        cache_supplied_name=request.cache_supplied_name,
        allow_ortholog_fallback=request.allow_ortholog_fallback,
        ortholog_override=(
            request.ortholog_override.model_dump()
            if request.ortholog_override is not None
            else None
        ),
        ortholog_catalog=list(request.ortholog_profile_catalog or []),
    )


def _capture_subprocess_stderr() -> bool:
    raw = os.getenv("WORKER_JOB_CAPTURE_STDERR", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _job_wall_timeout_sec() -> float | None:
    raw = os.getenv("WORKER_JOB_WALL_TIMEOUT_SEC", "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    if value <= 0:
        return None
    return value


def _subprocess_env(*, job_id: str | None) -> dict[str, str]:
    env = os.environ.copy()
    for key in _SUBPROCESS_ENV_KEYS:
        value = os.getenv(key)
        if value is not None:
            env[key] = value
    if job_id is not None:
        env["ANNOTATION_JOB_ID"] = job_id
    env["WORKER_JOB_EXECUTION"] = "inprocess"
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


def parse_progress_stderr_line(line: str) -> JobProgressEvent | None:
    """Parse one subprocess stderr line as a progress NDJSON record.

    Returns None for blank lines, non-JSON log noise, JSON that isn't a
    `{"type": "progress", ...}` object, or a progress object whose fields
    fail `JobProgressEvent` validation.
    """
    text = line.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or payload.get("type") != "progress":
        return None
    fields = {key: value for key, value in payload.items() if key != "type"}
    try:
        return JobProgressEvent(**fields)
    except ValidationError:
        return None


def _drain_subprocess_streams(
    proc: subprocess.Popen,
    *,
    on_progress,
    on_log,
    capture_stderr: bool,
):
    """Start background readers for stdout/stderr while the process runs.

    stdout is buffered verbatim for the final result JSON. stderr is read
    line-by-line: progress NDJSON records are dispatched to `on_progress`;
    everything else is forwarded to `on_log` (if given) and/or kept in a
    bounded tail buffer for failure diagnostics when `capture_stderr` is
    True. Non-progress stderr is never written to the live terminal here.
    """
    stdout_chunks: list[str] = []
    stderr_tail: list[str] = []
    stderr_tail_len = 0

    def _read_stdout() -> None:
        assert proc.stdout is not None
        try:
            while True:
                chunk = proc.stdout.read(65536)
                if not chunk:
                    break
                stdout_chunks.append(chunk)
        finally:
            try:
                proc.stdout.close()
            except (OSError, ValueError):
                pass

    def _read_stderr() -> None:
        nonlocal stderr_tail_len
        assert proc.stderr is not None
        try:
            for raw_line in proc.stderr:
                line = raw_line.rstrip("\n")
                if not line:
                    continue
                event = parse_progress_stderr_line(line)
                if event is not None:
                    if on_progress is not None:
                        try:
                            on_progress(event)
                        except Exception:
                            pass
                    continue
                if on_log is not None:
                    try:
                        on_log(line)
                    except Exception:
                        pass
                if capture_stderr:
                    stderr_tail.append(line)
                    stderr_tail_len += len(line) + 1
                    while stderr_tail_len > _STDERR_LOG_TAIL_LIMIT_CHARS and len(stderr_tail) > 1:
                        removed = stderr_tail.pop(0)
                        stderr_tail_len -= len(removed) + 1
        finally:
            try:
                proc.stderr.close()
            except (OSError, ValueError):
                pass

    stdout_thread = threading.Thread(target=_read_stdout, daemon=True)
    stderr_thread = threading.Thread(target=_read_stderr, daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    return stdout_thread, stderr_thread, stdout_chunks, stderr_tail


def _wait_with_optional_timeout(proc: subprocess.Popen, *, timeout_sec: float | None) -> bool:
    """Wait for process exit. Returns True if it was killed for exceeding timeout_sec."""
    if timeout_sec is None:
        proc.wait()
        return False
    deadline = time.monotonic() + timeout_sec
    try:
        proc.wait(timeout=max(0.1, deadline - time.monotonic()))
        return False
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        return True


def _run_subprocess(
    request: AnnotationJobRequest,
    *,
    job_id: str | None = None,
    on_progress=None,
    on_log=None,
):
    request_path = None
    proc: subprocess.Popen | None = None
    capture_stderr = _capture_subprocess_stderr()
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            delete=False,
        ) as request_file:
            json.dump(request.model_dump(mode="json"), request_file)
            request_path = request_file.name

        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "worker.job_main",
                "--request-file",
                request_path,
            ],
            env=_subprocess_env(job_id=job_id),
            # stderr is always piped (not inherited) so progress NDJSON can
            # be parsed; non-progress lines are never dumped to the live
            # terminal by default. stdout stays the single JSON result.
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        _register_job_process(job_id, proc)

        stdout_thread, stderr_thread, stdout_chunks, stderr_tail = _drain_subprocess_streams(
            proc,
            on_progress=on_progress,
            on_log=on_log,
            capture_stderr=capture_stderr,
        )

        wall_timeout_sec = _job_wall_timeout_sec()
        timed_out = _wait_with_optional_timeout(proc, timeout_sec=wall_timeout_sec)
        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)

        stdout = "".join(stdout_chunks).strip()
        stderr_detail = "\n".join(stderr_tail).strip()

        if timed_out:
            raise RuntimeError(
                f"annotation subprocess exceeded WORKER_JOB_WALL_TIMEOUT_SEC="
                f"{wall_timeout_sec:g}s"
                + (f": {stderr_detail}" if stderr_detail else "")
            )
        if proc.returncode != 0:
            if not stderr_detail and not capture_stderr:
                stderr_detail = (
                    "annotation subprocess stderr was not captured; "
                    "set WORKER_JOB_CAPTURE_STDERR=1 to capture failure diagnostics"
                )
            raise RuntimeError(
                f"annotation subprocess failed with exit code {proc.returncode}"
                + (f": {stderr_detail}" if stderr_detail else "")
            )
        if not stdout:
            raise RuntimeError("annotation subprocess produced no stdout")
        try:
            return json.loads(stdout)
        except json.JSONDecodeError as exc:
            preview = stdout[:200].replace("\n", "\\n")
            raise RuntimeError(
                f"annotation subprocess stdout is not valid JSON: {exc}; "
                f"preview={preview!r}"
            ) from exc
    finally:
        if proc is not None:
            _unregister_job_process(job_id, proc)
        if request_path is not None:
            os.unlink(request_path)


def run_annotation_job(
    request: AnnotationJobRequest,
    *,
    job_id: str | None = None,
    annotation_main=None,
    on_progress=None,
    on_log=None,
):
    if os.getenv("WORKER_JOB_EXECUTION", "subprocess") == "inprocess":
        return _run_inprocess(request, annotation_main=annotation_main, progress_cb=on_progress)
    return _run_subprocess(request, job_id=job_id, on_progress=on_progress, on_log=on_log)
