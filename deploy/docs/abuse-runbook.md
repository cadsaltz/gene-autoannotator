# Abuse runbook

What to do when someone floods the queue, spams sign-ups, or a worker token
leaks. Run commands on the backend host from the repo root:

```bash
DC="docker compose -f deploy/compose/docker-compose.backend.yml"
```

Admin alerts (`backend/alerts.py`) email every active admin when the queue
passes `ALERT_QUEUE_DEPTH`, jobs wait `ALERT_NO_WORKER_MINUTES` with no worker,
or the last hour's failure rate passes `ALERT_FAILURE_RATE`. They are usually
the first signal; confirm on **/admin** (queue, workers, suspended users,
active limits).

## 1. Find the account

- **/admin/users**: search by email; the row shows active jobs and jobs in the
  last 24 h. **Audit** opens that user's events.
- **/admin/audit**: filter by action (`signup`, `login_code_sent`,
  `job_submit`, `batch_submit`, ...) or user ID. The Actor column shows the
  client IP.
- CLI: `$DC exec backend python -m backend.manage list-users --query SUBSTRING`

## 2. Suspend and sign out

Suspending blocks sign-in and revokes all sessions immediately.

- **/admin/users**: set Status to `suspended`, **Save**.
- CLI (also works with no admin session; audited as `"source": "cli"`):

  ```bash
  $DC exec backend python -m backend.manage set-status EMAIL suspended
  $DC exec backend python -m backend.manage revoke-sessions EMAIL   # sign out only
  ```

Undo with `set-status EMAIL active`.

## 3. Cancel the flood

**Suspending does not cancel queued jobs, and workers still run them.** Cancel
them explicitly:

- **All queued jobs for one user** (not written to the audit log):

  ```bash
  $DC exec backend python -c 'import sys; from backend.auth_store import AuthStore; from backend.job_store import JobStore; from backend.db_path import DEFAULT_DB_PATH as P; u = AuthStore(P).get_user_by_email(sys.argv[1]); print(JobStore(P).cancel_queued_for_user(u["id"]), "queued job(s) cancelled")' EMAIL
  ```

- **Individual or running jobs**: **/jobs** as an admin shows every user's jobs
  with **Cancel** buttons (audited as `job_cancel`). It lists only the newest
  100 jobs and does not show the submitter.
- **Delete the account**: **Delete** on /admin/users revokes sessions and
  cancels the user's queued jobs (not running ones). It cannot be undone and
  frees the email to sign up again, so prefer suspend.

## 4. Tighten limits

Edit `.env` at the repo root, then recreate the backend (`restart` does not
re-read `.env`):

```bash
$DC up -d --force-recreate backend
```

| Variable | Effect |
|----------|--------|
| `MAX_QUEUED_JOBS` | Non-admin submissions get HTTP 429 once this many jobs are queued |
| `USER_MAX_ACTIVE_JOBS`, `USER_MAX_JOBS_PER_DAY`, `USER_MAX_BATCH_SIZE` | Per-user defaults |
| `IP_SIGNUPS_PER_DAY`, `IP_LOGINS_PER_HOUR`, `IP_SUBMITS_PER_HOUR` | Per client IP |
| `OTP_SENDS_PER_EMAIL_PER_HOUR` | Sign-in codes per email address |

`0` means **unlimited** for every one of these, so use `1` for the tightest
setting; there is no switch that pauses all submissions. To restrict one user
without editing `.env`, set their quota overrides on /admin/users (no restart
needed; `0` is unlimited there too). Rate-limit counters live in SQLite and survive the restart. Check that
/admin shows the new values.

If every audit event shows the same IP (the proxy's), the per-IP limits are
shared by everyone. Set `TRUST_FORWARDED_FOR=1` only when a proxy that
overwrites `X-Forwarded-For` (for example Caddy) sits in front of the backend.

## 5. Rotate `WORKER_API_TOKEN`

Do this if the token leaks. Every holder must change together; until they do,
worker and dispatcher calls get HTTP 401.

1. Generate: `deploy/scripts/generate-worker-token.sh`
2. Backend: set `WORKER_API_TOKEN` in `.env` (keep
   `REQUIRE_WORKER_API_TOKEN=1`), then `$DC up -d --force-recreate backend`.
3. HPC: update `WORKER_API_TOKEN` in `dispatcher.env` and in the
   `worker.run.env` that `WORKER_RUN_ENV_FILE` points to. Cancel the running
   worker so the next dispatcher tick relaunches it with the new token:
   `scancel --name gene-autoannotator-run`. Its claimed job is requeued once
   its lease (`LEASE_SECONDS`) expires.
4. Other workers: update `worker.env` (systemd installs use
   `/etc/gene-autoannotator/worker.env`) and restart the worker, e.g.
   `sudo systemctl restart gene-autoannotator-worker`.
5. Confirm workers show online on /admin.

## 6. Edge protection (future)

Once DNS is on Cloudflare (proxied records), turn on **"I'm Under Attack" mode**
in the zone's security settings during a sign-up or request flood, and turn it
off afterwards. It is not available until then.

## 7. Afterwards

Review **/admin/audit** for `status_change`, `sessions_revoked`, `job_cancel`,
and `user_delete` to confirm what happened, and restore any limits you
lowered.
