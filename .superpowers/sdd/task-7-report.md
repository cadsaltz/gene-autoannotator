# Task 7 Report: Auth API routes (`/auth/*`)

## Status

**Complete.** Implemented with TDD, tested, and committed on `feat/passwordless-otp-accounts`.

## Commit

- `9d6c6ae9d6a59c7c030a127b2dc3760e175f7827` — feat: add passwordless signup, login, OTP verify, me, and logout APIs

## What changed

### `backend/schemas.py`

- Added `AuthSignupRequest`, `AuthLoginRequest`, `AuthVerifyRequest`, `AuthOkResponse`, `AuthMeResponse` (EmailStr-backed).

### `backend/api.py`

- `create_app(..., auth_store=None)` defaults to `AuthStore(store.db_path)`.
- Routes: `POST /auth/signup`, `POST /auth/login`, `POST /auth/verify`, `GET /auth/me`, `POST /auth/logout`.
- Signup creates user if missing (keeps existing username on re-signup), always issues OTP via console/Resend sender.
- Login is anti-enumeration: unknown email returns `{ok: true}` without emailing; known users get OTP (`purpose="login"`).
- Verify consumes hashed OTP; on failure calls `register_failed_code_attempt` then 401 `"Invalid or expired code"`. Success marks verified, creates session, sets `ga_session` cookie (`httponly`, `samesite=lax`, `secure` from `SESSION_COOKIE_SECURE`, `max_age=SESSION_TTL_SECONDS`, `path=/`).
- `/auth/me` and internal `require_user` slide session expiry via `touch_session`. Logout deletes session and clears cookie (204).
- `/jobs` not gated yet (Task 8).

### `requirements-web.txt`

- Added `email-validator` for Pydantic `EmailStr`.

### `tests/test_coordinator_auth_api.py`

- Signup → OTP outbox → verify cookie → `/auth/me`.
- Wrong code → 401.
- Unknown login email → opaque 200, empty outbox.

## TDD evidence

1. Tests first; failed with `TypeError: create_app() got an unexpected keyword argument 'auth_store'`.
2. After implementation: `pytest tests/test_coordinator_auth_api.py -v` — 3 passed.

## Test results

```text
pytest tests/test_coordinator_auth_api.py -v → 3 passed
```

## Concerns / follow-ups

- CORS still has `allow_credentials=False`; cross-origin browser cookie auth will need that flipped (and origin allowlist) before a separate frontend can use session cookies.
- Per-email OTP send rate limiting deferred (Phase D); attempt lockout + schema validation only.
- `require_user` is ready but not yet applied to `/jobs` (Task 8).
- New test file required `git add -f` because root `tests/` is gitignored.

## Important review fix (logout cookie)

**Finding:** `_clear_session_cookie` only passed `path="/"`; browsers may not clear `ga_session` unless `delete_cookie` matches `set_cookie` attributes (`httponly`, `secure`, `samesite`).

**Fix:** Mirror `_set_session_cookie` flags on `response.delete_cookie` in `backend/api.py`.

**Test:** Added `test_logout_clears_session` — signup → verify → logout (204) → `/auth/me` returns 401.

**Verification:**

```text
.venv/bin/pytest tests/test_coordinator_auth_api.py -v → 4 passed
```

**Commit:** `a67f0bb8ce0086e48b84a6f350e7c591e74f23ac` — fix: mirror session cookie flags on logout clear
