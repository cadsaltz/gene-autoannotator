from backend import email_sender
from backend.auth import new_otp_code


def test_console_backend_records_send(monkeypatch):
    monkeypatch.setenv("EMAIL_BACKEND", "console")
    email_sender._CONSOLE_OUTBOX.clear()
    email_sender.send_login_code_email(to_email="a@example.com", code="123456")
    assert len(email_sender._CONSOLE_OUTBOX) == 1
    assert email_sender._CONSOLE_OUTBOX[0]["to"] == "a@example.com"
    assert email_sender._CONSOLE_OUTBOX[0]["code"] == "123456"


def test_otp_code_is_six_digits():
    code = new_otp_code()
    assert len(code) == 6
    assert code.isdigit()
