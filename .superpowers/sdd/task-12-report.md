# Task 12 Report: End-to-end smoke + env docs

## Status

**Complete.** USAGE passwordless section + checklist; `coordinator.env.example` auth comments; auth API smoke green; committed on `feat/passwordless-otp-accounts`.

## Automated smoke

```text
EMAIL_BACKEND=console pytest tests/test_coordinator_auth_api.py -v
→ 6 passed
```

Covers: signup/OTP verify + `ga_session`, wrong OTP 401, logout, unauthenticated `POST /jobs` 401, signed-in job create 201.

## Docs

- **USAGE.md:** `## Passwordless accounts` (console vs Resend, operator flow, manual checklist with pytest rows marked ✅).
- **coordinator.env.example:** pointer to USAGE + `SESSION_COOKIE_SECURE` note.

## Manual / UI (human)

- 5-attempt OTP invalidation; worker Bearer vs session; `REQUIRE_WORKER_API_TOKEN=1` → 503 on queue-summary; `/jobs` → `/login` redirect.

## Commit

- `d9243d0` — docs: document passwordless account setup for local and Resend

## Final-review follow-up

`require_user` now injects `Response` and re-sets `ga_session` with refreshed `Max-Age=SESSION_TTL_SECONDS` after `touch_session`, so browser cookie expiry slides with SQLite. Covered by `test_auth_me_refreshes_session_cookie_max_age` (7 auth API tests green).
