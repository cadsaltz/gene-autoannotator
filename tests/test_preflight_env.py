import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "deploy" / "scripts" / "preflight-env.sh"

COMPLETE = """\
# comment
MONGO_URI=mongodb://user:s3cret-mongo@db:27017/gene
WORKER_API_TOKEN="tok-s3cret"
REQUIRE_WORKER_API_TOKEN=1
SESSION_COOKIE_SECURE=1
export EMAIL_BACKEND=resend  # inline comment
RESEND_API_KEY='re_s3cret'
EMAIL_FROM=Gene Autoannotator <noreply@example.org>
"""


def _run(tmp_path, text):
    env_file = tmp_path / ".env"
    env_file.write_text(text, encoding="utf-8")
    return subprocess.run(
        ["bash", str(SCRIPT), str(env_file)],
        capture_output=True,
        text=True,
        timeout=30,
    )


def _lines(result):
    return result.stdout.strip().splitlines()


def test_complete_env_passes_and_never_prints_values(tmp_path):
    result = _run(tmp_path, COMPLETE)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _lines(result) == [
        "OK MONGO_URI",
        "OK WORKER_API_TOKEN",
        "OK REQUIRE_WORKER_API_TOKEN",
        "OK SESSION_COOKIE_SECURE",
        "OK EMAIL_BACKEND",
        "OK RESEND_API_KEY",
        "OK EMAIL_FROM",
    ]
    output = result.stdout + result.stderr
    for secret in ("s3cret", "noreply@example.org", "mongodb://", "resend\n"):
        assert secret not in output


def test_missing_and_empty_values_fail(tmp_path):
    text = COMPLETE.replace('WORKER_API_TOKEN="tok-s3cret"', "WORKER_API_TOKEN=").replace(
        "RESEND_API_KEY='re_s3cret'\n", ""
    )
    result = _run(tmp_path, text)
    assert result.returncode == 1
    assert "MISSING WORKER_API_TOKEN" in _lines(result)
    assert "MISSING RESEND_API_KEY" in _lines(result)
    assert "OK MONGO_URI" in _lines(result)
    assert "s3cret" not in result.stdout + result.stderr


def test_empty_quoted_value_counts_as_missing(tmp_path):
    result = _run(tmp_path, COMPLETE.replace("SESSION_COOKIE_SECURE=1", 'SESSION_COOKIE_SECURE=""'))
    assert result.returncode == 1
    assert "MISSING SESSION_COOKIE_SECURE" in _lines(result)


def test_mongodb_uri_alias_and_console_email_backend(tmp_path):
    text = (
        "MONGODB_URI=mongodb://db/gene\n"
        "WORKER_API_TOKEN=tok\n"
        "REQUIRE_WORKER_API_TOKEN=1\n"
        "SESSION_COOKIE_SECURE=1\n"
        "EMAIL_BACKEND=console\n"
    )
    result = _run(tmp_path, text)
    assert result.returncode == 0, result.stdout
    assert "OK MONGO_URI" in _lines(result)
    assert not any("RESEND_API_KEY" in line or "EMAIL_FROM" in line for line in _lines(result))


def test_later_assignment_wins(tmp_path):
    result = _run(tmp_path, COMPLETE + "WORKER_API_TOKEN=\n")
    assert result.returncode == 1
    assert "MISSING WORKER_API_TOKEN" in _lines(result)


def test_missing_env_file_exits_2(tmp_path):
    result = subprocess.run(
        ["bash", str(SCRIPT), str(tmp_path / "nope.env")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 2
    assert "MISSING env file" in result.stderr
