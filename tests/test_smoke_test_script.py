import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "smoke_test.py"


def _load():
    spec = importlib.util.spec_from_file_location("smoke_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


smoke = _load()


def test_refuses_without_explicit_confirmation(capsys):
    with pytest.raises(SystemExit) as excinfo:
        smoke.main(["http://example.invalid", "--otp-prompt", "--no-simulate-worker"])
    assert excinfo.value.code == 2
    assert "--i-understand-this-creates-accounts" in capsys.readouterr().err


def test_worker_steps_need_a_token(monkeypatch, capsys):
    monkeypatch.delenv("WORKER_API_TOKEN", raising=False)
    with pytest.raises(SystemExit) as excinfo:
        smoke.main(["http://example.invalid", "--otp-prompt", "--i-understand-this-creates-accounts"])
    assert excinfo.value.code == 2
    assert "WORKER_API_TOKEN" in capsys.readouterr().err


def test_otp_log_file_returns_only_a_new_code_for_that_email(tmp_path):
    log = tmp_path / "backend.log"
    log.write_text(
        "[email:console] to=Admin@Example.org code=111111\n"
        "[email:console] to=other@example.org code=222222\n",
        encoding="utf-8",
    )
    source = smoke.OtpSource(log_file=log, timeout=1)
    seen = source.mark("admin@example.org")
    with pytest.raises(smoke.SmokeAbort):
        source.wait("admin@example.org", seen)
    with log.open("a", encoding="utf-8") as handle:
        handle.write("[email:console] to=admin@example.org code=333333\n")
    assert source.wait("admin@example.org", seen) == "333333"


def test_test_accounts_are_smoke_aliases_of_the_admin_address():
    args = smoke.build_parser().parse_args(
        ["https://example.org", "--otp-prompt", "--admin-email", "ops+alerts@example.org"]
    )
    args.worker_token = None
    run = smoke.Smoke(args)
    for email in (run.user_email, run.other_email):
        assert email.startswith("ops+smoke-") and email.endswith("@example.org")
    assert run.user_email != run.other_email
