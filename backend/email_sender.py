import os

_CONSOLE_OUTBOX: list[dict] = []


def send_login_code_email(*, to_email: str, code: str) -> None:
    backend = os.getenv("EMAIL_BACKEND", "console").strip().lower()
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
        import resend

        resend.api_key = os.environ["RESEND_API_KEY"]
        from_addr = os.environ["EMAIL_FROM"]
        resend.Emails.send(
            {
                "from": from_addr,
                "to": [to_email],
                "subject": subject,
                "text": body,
            }
        )
        return
    raise RuntimeError(f"Unknown EMAIL_BACKEND={backend!r}")
