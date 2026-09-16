# Task 6 Report: Email sender + OTP helpers

## Status

**Complete.** Implemented with TDD, tested, and committed on `feat/passwordless-otp-accounts`.

## Commit

- `45e5a435c3d2a41de4900e1f0dcc48e6e82cb1ba` — feat: add OTP email sender and auth secret helpers

## What changed

### `backend/auth.py` (new)

- Constants: `SESSION_COOKIE_NAME`, `OTP_TTL_SECONDS`, `OTP_MAX_ATTEMPTS`, `SESSION_TTL_SECONDS`.
- `hash_secret`, `new_session_token`, `new_otp_code` (6-digit zero-padded).

### `backend/email_sender.py` (new)

- Console backend (default): appends to `_CONSOLE_OUTBOX`, prints dev log line.
- Resend backend when `EMAIL_BACKEND=resend` (uses `RESEND_API_KEY`, `EMAIL_FROM`).

### `requirements-web.txt`

- Added `resend`.

### `coordinator.env.example`

- `EMAIL_BACKEND`, commented Resend vars, `SESSION_COOKIE_SECURE=0`.

### `tests/test_coordinator_email_sender.py` (new)

- Console outbox recording and OTP format checks.

## TDD evidence

1. Added tests first; collection failed with missing `email_sender` / `auth`.
2. After implementation: `pytest tests/test_coordinator_email_sender.py -v` — 2 passed.

## Test results

```text
pytest tests/test_coordinator_email_sender.py -v → 2 passed
```

## Concerns / follow-ups

- Resend path is not integration-tested (would need live API key); console path covers dev flow.
- `hash_secret` uses plain SHA-256; acceptable for OTP/session token hashing if combined with high-entropy secrets (later tasks may add pepper/slow hash for codes).
