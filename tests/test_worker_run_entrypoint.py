import os
import subprocess
from pathlib import Path


def test_entrypoint_copies_read_only_worker_env_to_writable_path(tmp_path):
    source_env = tmp_path / "mounted-worker.env"
    source_env.write_text("BACKEND_URL=https://backend.example\n", encoding="utf-8")
    source_env.chmod(0o444)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    captured_path = tmp_path / "captured-worker-env-path"
    fake_python = bin_dir / "python"
    fake_python.write_text(
        "#!/usr/bin/env bash\n"
        'printf "%s" "$WORKER_ENV_FILE" > "$CAPTURED_ENV_PATH"\n'
        '[[ "$WORKER_ENV_FILE" != "$ORIGINAL_ENV_PATH" ]]\n'
        'cmp "$WORKER_ENV_FILE" "$ORIGINAL_ENV_PATH"\n'
        'printf "WORKER_NAME=test-worker\\n" >> "$WORKER_ENV_FILE"\n',
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["bash", str(repo_root / "deploy/docker/worker-run-entrypoint.sh")],
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "WORKER_ENV_FILE": str(source_env),
            "ORIGINAL_ENV_PATH": str(source_env),
            "CAPTURED_ENV_PATH": str(captured_path),
            "WORKER_OUTPUT_DIR": str(tmp_path / "out"),
            "WORKER_CACHE_DIR": str(tmp_path / "cache"),
            "OLLAMA_MODELS": str(tmp_path / "models"),
            "REQUIRE_GPU": "0",
        },
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    copied_env = Path(captured_path.read_text(encoding="utf-8"))
    assert copied_env.parent == Path(os.environ.get("TMPDIR", "/tmp"))
    assert source_env.read_text(encoding="utf-8") == (
        "BACKEND_URL=https://backend.example\n"
    )
    assert copied_env.read_text(encoding="utf-8").endswith(
        "WORKER_NAME=test-worker\n"
    )
