# Data inventory, retention, and secrets

What the service stores about people, where, who can read it, and how long it
stays. It is the factual input for the Privacy Policy (`/legal/privacy`) and
reflects the code as of this branch; update it when a store or log changes.
Commands use `$DC` from [deploy/README.md](../README.md):

```bash
DC="docker compose -p gaa -f deploy/compose/docker-compose.prod.yml --env-file deploy/compose/compose.env"
```

## Where data lives

| Store | Location in production | Contents |
|-------|------------------------|----------|
| Control-plane SQLite | `backend/jobs.sqlite3` in volume `gaa_backend-data` (`/state/backend` in the backend container) | Accounts, sessions, sign-in codes, jobs, batches, workers, audit log, rate-limit counters |
| Profiles | Volume `gaa_profiles-data` (`/app/data/profiles`) | Organism profile JSON files (no personal data) |
| MongoDB `gene_autoannotator.annotations` | Atlas | Shared annotation library: one document per gene, current result plus older versions |
| MongoDB GridFS `control_plane_backups` (`control_plane_backups.files` / `.chunks`, same database) | Atlas | Snapshots of the SQLite file and the profiles |
| Container logs | Docker `json-file`, 5 × 10 MB per container (`x-logging` in `docker-compose.prod.yml`) | Caddy access logs, backend (uvicorn) access and app logs, frontend logs |
| Browser | Cookie `ga_session` | Session token |
| Email provider (Resend) | Resend account | Recipient address and body of each sign-in code and admin alert |
| HPC | Shared filesystem of the Slurm cluster | Job requests and annotation outputs of the jobs workers ran |

The frontend stores nothing server-side and uses no `localStorage`.

## Fields collected

### SQLite (`backend/jobs.sqlite3`)

| Table | Fields | Written when | Removed when |
|-------|--------|--------------|--------------|
| `users` | `id`, `email`, `username` (optional, from the sign-up form), `email_verified`, `role`, `status`, `quota_max_active`, `quota_max_per_day`, `quota_max_batch`, `terms_version`, `terms_accepted_at`, `last_login_at`, `created_at` | Sign-up (the row exists before the code is verified) | Admin deletes the account |
| `sessions` | `id`, `user_id`, `token_hash` (SHA-256 of the cookie value), `ip` (client IP at sign-in), `created_at`, `last_seen_at`, `expires_at` (90 days, sliding) | Code verified | Sign-out, admin revoke, suspension, account deletion. **Expired rows are not purged.** |
| `login_codes` | `id`, `email`, `purpose` (`signup`/`login`), `code_hash` (SHA-256 of the 6-digit code), `expires_at` (10 minutes), `used_at`, `attempt_count`, `created_at` | Each code sent | Account deletion only. **Used and expired codes are not purged.** |
| `annotation_jobs` | `request_json` (profile, organism, strain, locus, gene name, target preflight, profile snapshot), `result_json`, `error`, status and progress fields, `worker_id`, `submitted_by_user_id`, `output_path` (path on the worker), timestamps | Submission; updated by workers | `JOB_RETENTION_DAYS` purge (finished jobs only), or an admin's `DELETE /jobs/history` (all finished jobs) |
| `annotation_batches` | Options, input summary (the submitted gene list after parsing), `submitted_by_user_id`, `created_at` | Batch submission | Retention purge once older than the cutoff and without jobs |
| `audit_events` | `action`, `actor_user_id`, `target_type`, `target_id`, `ip`, `details_json`, `created_at` | See below | **Never** (no pruning) |
| `rate_events` | `bucket`, `key` (client IP, or the lower-cased email for `otp_send`), `created_at` | Each sign-up, sign-in request, code sent, and non-admin submission | On the next event in the same bucket once older than 2 days |
| `workers` | Worker name, hostname, agent version, memory, slots, state, Ollama models, heartbeats | Worker registration | Worker deregisters (HPC workers do on exit) |

Audit actions: `signup` (details: `terms_version`), `login_code_sent`,
`login`, `logout`, `job_submit`, `batch_submit`, `job_cancel`,
`profile_create`, `profile_update`, `profile_delete`, `role_change`,
`status_change`, `quota_change`, `sessions_revoked`, `jobs_cancelled` (CLI),
`user_delete` (details include the deleted **email**), `jobs_purged`,
`backup_created`, `backup_restored`. The `ip` column is the client IP
(`TRUST_FORWARDED_FOR=1` behind Caddy); CLI and system events have none.

### MongoDB

- `annotations`: `_id` (`<profile>:<locus>` or `<profile>:name:<slug>`),
  profile and organism names, locus, gene name, `current` (`job_id`,
  `generated_at`, `gene_name`, `output_path`, `result`), `versions` (earlier
  `current` values), `search_text`, `updated_at`. **No user id or email.**
  Written when a job completes, whoever submitted it. Documents written
  before key redaction may contain NCBI API keys inside request URLs until
  `scripts/redact_mongo_secrets.py --apply` has run (launch runbook step 5).
- `control_plane_backups`: a `.tar.gz` of a consistent copy of the whole SQLite
  file (every table above) plus the profile files; metadata `created_at`,
  `app_version`, `db_bytes`.

### Logs

- **Caddy** (JSON on stdout): client IP, method, full URI including query
  strings (for example `/api/backend/admin/users?query=<email fragment>`),
  status, user agent, timing. Caddy redacts the `Cookie` and `Authorization`
  headers.
- **Backend** (uvicorn access log): method, path with query string, status;
  the address is Caddy's container IP (`--no-proxy-headers`). App logs include
  job ids, worker names, and warnings. With `EMAIL_BACKEND=console` (staging
  only) every sign-in code and recipient address is printed.
- **Frontend**: errors only.
- Docker rotates by size (5 × 10 MB per container), so the time covered
  depends on traffic; `docker compose down` or recreating a container deletes
  its logs.

### Outside the server

- **Resend** receives each recipient address and message (sign-in codes,
  admin alerts) and keeps delivery logs per its own retention.
- **MongoDB Atlas** hosts the annotation library and the backups.
- **HPC workers** receive a job's stored request (profile, locus, gene name,
  profile snapshot) and its job id, never the submitter's identity. Outputs go
  to the cluster's shared filesystem (`WORKER_OUTPUT_DIR`, default
  `gen_json` under the checkout) and the worker's logs.
- **Cloudflare**, if DNS is proxied, sees every request (IP, URL, headers).
- **GitHub (GHCR)** holds images with code only; `.dockerignore` keeps env
  files and databases out.

## Who can see what

| Who | Can see |
|-----|---------|
| Anyone | Homepage, `/legal/*`, `robots.txt` |
| Signed-in user | Own account (`/auth/me`), own jobs, batches, and results, queue position and own quota usage, the whole annotation library (every completed gene, from anyone's job, without submitter), organism profiles |
| Admin | Everything above for all users, plus every account (email, role, status, quotas, last sign-in, job counts), submitter email on every job, the audit log with client IPs, workers and health, quota settings |
| Operator with server access | Everything in SQLite, env files (secrets), container logs; with the backend's Mongo user also backups |
| Holder of the frontend's Mongo user | Whatever its Atlas role allows; with the built-in `read` role on `gene_autoannotator` that includes the backups (see Secrets) |
| HPC account holders | Job requests and outputs on the shared filesystem, worker logs |

A completed job's result joins the shared library, so any signed-in user can
find which genes have been annotated (not by whom).

## Retention

| Data | Kept for | Set by |
|------|----------|--------|
| Account (`users`) | Until an admin deletes it | Manual |
| Sessions | 90 days after last use for sign-in; rows stay until sign-out, revoke, suspension, or deletion | `SESSION_TTL_SECONDS` in `backend/auth.py` |
| Sign-in codes | Valid 10 minutes; rows stay until the account is deleted | `OTP_TTL_SECONDS` |
| Finished jobs and empty batches | `JOB_RETENTION_DAYS` after they finished (checked daily); `0` (the default and the prod example) keeps them forever | `JOB_RETENTION_DAYS` |
| Queued/running jobs | Until they finish | |
| Audit log | Forever | No setting |
| Rate-limit events | About 2 days | `PRUNE_AFTER` in `backend/rate_limits.py` |
| Annotation library | Forever, including earlier versions; not touched by `JOB_RETENTION_DAYS` | No setting |
| Backups | Newest `BACKUP_KEEP` snapshots, one every `BACKUP_INTERVAL_SECONDS` (prod example: 48 hourly = 2 days; code defaults: 28 × 6 h = 7 days) | `BACKUP_KEEP`, `BACKUP_INTERVAL_SECONDS` |
| Container logs | 50 MB per container, rotated by size | `x-logging` in the compose file |
| Resend logs | Resend's retention | Resend |

Before launch, pick a `JOB_RETENTION_DAYS` value and state it in the Privacy
Policy (the purge removes SQLite rows only; result files on HPC and the
annotation library stay).

## Account deletion

1. The user emails the contact address from the Privacy Policy.
2. An admin opens **/admin/users**, finds the email, and clicks **Delete**
   (`DELETE /admin/users/{id}`; there is no CLI command). The last admin cannot
   be deleted.
3. Immediately removed from SQLite: the `users` row, all `sessions`, and all
   `login_codes` for the email. Queued jobs are cancelled; running jobs keep
   running and finish normally.
4. Left in SQLite: the user's job and batch rows (with the now-dangling
   `submitted_by_user_id`) until the retention purge; audit events with the
   user's id and IPs (never purged), plus a `user_delete` event that records
   the email; `rate_events` keyed by the email for up to about 2 days.
5. Backups: snapshots taken before the deletion still contain the account.
   They age out after `BACKUP_KEEP` further snapshots, i.e. `BACKUP_KEEP` ×
   `BACKUP_INTERVAL_SECONDS` (2 days with the prod example).
6. Annotation library: unaffected (it holds no user identity).
7. Resend keeps its delivery logs per its retention.

The Privacy Policy must describe steps 4 to 7 honestly, or the gaps must be
closed first (see "Open retention gaps").

## Open retention gaps

Decisions for the owner before the Privacy Policy is final; none of these is
automated today:

- The audit log (IPs, and the email in `user_delete`) is kept forever.
- Expired sessions (with their IPs) and used or expired sign-in codes are
  never purged.
- Deleting an account keeps its jobs and audit events.
- `JOB_RETENTION_DAYS=0` keeps finished jobs forever.
- The frontend's Mongo user can read backups unless it gets the narrow custom
  role described below.

## Secrets

The real env files are gitignored (`deploy/compose/*.env`, `.env`,
`worker.env`, `dispatcher.env`, `worker.run.env`) and `.dockerignore` keeps
them out of images. `deploy/scripts/preflight-env.sh` checks them without
printing values.

| Secret | Where it is set | Used for |
|--------|-----------------|----------|
| `WORKER_API_TOKEN` | Server `deploy/compose/backend.env`; HPC `dispatcher.env` and the `worker.run.env` that `WORKER_RUN_ENV_FILE` points to; other workers' `worker.env` (`/etc/gene-autoannotator/worker.env` for systemd installs) | Worker and dispatcher calls (`Authorization: Bearer`) |
| `RESEND_API_KEY` | `backend.env` | Sending sign-in codes and admin alerts |
| Mongo read-write user | `MONGO_URI` in `backend.env`; also the shell that runs `scripts/redact_mongo_secrets.py` | Annotation writes, backups, restore |
| Mongo read-only user | `MONGO_URI` in `deploy/compose/frontend.env` | Annotation pages (direct reads of `annotations`) |
| `NCBI_API_KEY` (alias `ENTREZ_API_KEY`) | Workers: `worker.env` / `worker.run.env`; optionally `backend.env` (gene-name lookups during validation) | NCBI E-utilities rate limits |
| GHCR pull token (classic PAT, `read:packages` only) | `docker login ghcr.io` as root on the server (`/root/.docker/config.json`); `apptainer registry login` on the HPC login node | Pulling private images; not needed if the packages are public |
| Caddy ACME account and certificates | Volume `gaa_caddy-data` | TLS; back it up with the host, no rotation needed |

Session tokens and sign-in codes are stored only as SHA-256 hashes. Service
accounts (GitHub, Atlas, Resend, the registrar, Cloudflare) should have 2FA.

### Mongo users (Atlas → Database Access)

- Backend: `readWrite` on database `gene_autoannotator` (annotations and the
  GridFS bucket live there).
- Frontend: a custom role (Atlas → Database Access → Custom Roles) with only
  the `find` action on collection `gene_autoannotator.annotations`. The
  built-in `read` role on the database would also expose
  `control_plane_backups`, i.e. every account email and the audit log.
- Network Access: only the server's public IP (plus your own for the redaction
  script and restores run from a laptop).

### Rotation

After changing `backend.env` or `frontend.env`, recreate the container
(`restart` does not re-read env files):

```bash
$DC up -d --force-recreate backend    # or frontend
```

- **`WORKER_API_TOKEN`**: [abuse runbook § 6](abuse-runbook.md#6-rotate-worker_api_token).
- **`RESEND_API_KEY`**: Resend → API Keys → create a key with "Sending access"
  limited to the domain; put it in `backend.env`; recreate the backend; sign in
  once to confirm a code arrives; then delete the old key in Resend.
- **Mongo passwords**: create a second user with the same role, switch the
  env file to it, recreate that container, check (backend: `$DC exec -u app
  backend python -m backend.manage list-backups`; frontend: search on
  /annotations), then delete the old user. Editing the existing user's
  password instead breaks the running container until its env file is updated.
- **`NCBI_API_KEY`**: NCBI account → Account settings → API Key Management →
  create a new key (an account has one key; the new one replaces the old).
  Update every place in the table above; on the HPC the next worker run reads
  the new `worker.run.env` (`scancel --name gene-autoannotator-run` to apply it
  now). Rotate after running the Mongo redaction, since old annotation
  documents exposed the previous key.
- **GHCR token**: GitHub → Settings → Developer settings → Personal access
  tokens (classic) → regenerate; repeat `sudo docker login ghcr.io -u
  <github-user>` on the server and `apptainer registry login --username
  <github-user> docker://ghcr.io` on the HPC.
- **Sessions** (suspected cookie theft): `$DC exec -u app backend python -m
  backend.manage revoke-sessions EMAIL` per user; there is no global sign-out.
