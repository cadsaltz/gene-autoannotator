import json
import os
import subprocess
import sys
import tempfile

from shared.job_contract import AnnotationJobRequest

_SUBPROCESS_ENV_KEYS = (
    "OLLAMA_ROUTER_URL",
    "AUTOANNOTATION_MODEL_MODE",
    "AUTOANNOTATION_OLLAMA_KEEP_ALIVE",
    "WORKER_CACHE_DIR",
    "WORKER_OUTPUT_DIR",
)


def _load_annotation_main():
    from autoannotation import __main__ as annotation_cli

    return annotation_cli.main


def _run_inprocess(request: AnnotationJobRequest, annotation_main=None):
    main = annotation_main or _load_annotation_main()
    # Override paths from worker env, ignoring coordinator-sent paths for security.
    cache_dir = os.getenv("WORKER_CACHE_DIR", "./.cache")
    output_dir = os.getenv("WORKER_OUTPUT_DIR", "gen_json")
    return main(
        gene=None,
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
    )


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


def _run_subprocess(request: AnnotationJobRequest, *, job_id: str | None):
    request_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            delete=False,
        ) as request_file:
            json.dump(request.model_dump(mode="json"), request_file)
            request_path = request_file.name

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "worker.job_main",
                "--request-file",
                request_path,
            ],
            env=_subprocess_env(job_id=job_id),
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            stderr = completed.stderr.strip()
            raise RuntimeError(
                f"annotation subprocess failed with exit code {completed.returncode}"
                + (f": {stderr}" if stderr else "")
            )
        stdout = completed.stdout.strip()
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
        if request_path is not None:
            os.unlink(request_path)


def run_annotation_job(
    request: AnnotationJobRequest,
    *,
    job_id: str | None = None,
    annotation_main=None,
):
    if os.getenv("WORKER_JOB_EXECUTION", "subprocess") == "inprocess":
        return _run_inprocess(request, annotation_main=annotation_main)
    return _run_subprocess(request, job_id=job_id)
