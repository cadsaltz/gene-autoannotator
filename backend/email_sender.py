import logging
import os

log = logging.getLogger(__name__)

_CONSOLE_OUTBOX: list[dict] = []


def _email_backend() -> str:
    return os.getenv("EMAIL_BACKEND", "console").strip().lower()


def _send_via_resend(*, to_email: str, subject: str, body: str) -> None:
    try:
        import resend
    except ImportError as exc:  # pragma: no cover - env/packaging issue
        raise RuntimeError(
            "EMAIL_BACKEND=resend but the 'resend' package is not installed "
            "(pip install -r requirements-web.txt)"
        ) from exc

    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    from_addr = os.environ.get("EMAIL_FROM", "").strip()
    if not api_key:
        raise RuntimeError("RESEND_API_KEY is not set")
    if not from_addr:
        raise RuntimeError("EMAIL_FROM is not set")

    resend.api_key = api_key
    try:
        resend.Emails.send(
            {
                "from": from_addr,
                "to": [to_email],
                "subject": subject,
                "text": body,
            }
        )
    except Exception as exc:
        raise RuntimeError(f"Resend send failed: {exc}") from exc


def send_login_code_email(*, to_email: str, code: str) -> None:
    backend = _email_backend()
    subject = "Your Gene Autoannotator sign-in code"
    body = (
        f"Your sign-in code is: {code}\n\n"
        f"It expires in 10 minutes. If you did not request this, ignore this email.\n"
    )
    if backend == "console":
        _CONSOLE_OUTBOX.append({"to": to_email, "subject": subject, "code": code, "body": body})
        print(f"[email:console] to={to_email} code={code}")
        return
    if backend == "resend":
        _send_via_resend(to_email=to_email, subject=subject, body=body)
        return
    raise RuntimeError(f"Unknown EMAIL_BACKEND={backend!r}")


def send_admin_alert(to: str, subject: str, body: str) -> None:
    backend = _email_backend()
    if backend == "console":
        _CONSOLE_OUTBOX.append({"to": to, "subject": subject, "body": body})
        log.warning("[email:console] admin alert to=%s subject=%s\n%s", to, subject, body)
        return
    if backend == "resend":
        _send_via_resend(to_email=to, subject=subject, body=body)
        return
    raise RuntimeError(f"Unknown EMAIL_BACKEND={backend!r}")
