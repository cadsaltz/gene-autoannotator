# Launch-day runbook

Going public with minimal downtime once a domain is paid for. It builds on
[deploy/README.md](../README.md), which has the details of every compose
command used here; this page gives the order and the launch-only steps. Two
ways to launch:

- **Path A, cut over on the Pi**: the production compose stack replaces the
  running `docker-compose.backend.yml` stack on the Raspberry Pi, using the
  migration script. No new machine.
- **Path B, move to a new server**: the production stack runs on a new host
  and the control plane is restored there from the MongoDB backups.

Run commands from the repository root of the checkout the stack uses, with:

```bash
DC="docker compose -p gaa -f deploy/compose/docker-compose.prod.yml --env-file deploy/compose/compose.env"
```

Related: [data inventory, retention, and secrets](data-inventory.md),
[abuse runbook](abuse-runbook.md).

## Before launch day (no downtime)

1. **Legal text.** Every legal page (`/legal/terms`, `/legal/privacy`,
   `/legal/acceptable-use`, `/legal/disclaimer`) is a checklist rendered by
   `frontend/components/LegalPlaceholder.js` under a "DRAFT — pending legal
   review" banner. Replace them with the final text, using
   [data-inventory.md](data-inventory.md) for the Privacy Policy. Bracketed
   placeholders to fill:

   | Placeholder | File | Where it shows |
   |-------------|------|----------------|
   | `[contact email]` (`CONTACT_PLACEHOLDER`) | `frontend/lib/legal.js` | Site footer (`frontend/components/SiteFooter.js`), homepage FAQ on data deletion (`frontend/components/guide/FaqSection.js`), Terms, Privacy, and Acceptable Use checklists |
   | `[Operating entity]` | `frontend/lib/legal.js` | Terms ("Operating entity: [Operating entity]") and the Disclaimer draft wording |
   | `[Operating entity]` | `frontend/components/guide/DisclaimerSection.js` | Homepage disclaimer |
   | `[Paper citation — to be added]` (`CITATION_PLACEHOLDER`) | `frontend/components/guide/CreditsSection.js` | Homepage "How to cite" |

   `frontend/components/legal.test.js` and
   `frontend/components/guide/guide.test.js` assert some of these strings;
   update them with the text. When the final terms go live, bump
   `TERMS_VERSION` in `frontend/lib/legal.js` and `DEFAULT_TERMS_VERSION` in
   `backend/api.py` together (currently `draft-2026-09`), or set
   `TERMS_VERSION` in `backend.env` to the same value.
2. **Retention.** Choose `JOB_RETENTION_DAYS` (the prod example keeps jobs
   forever) and `AUDIT_RETENTION_DAYS` (default 365), and decide on the open
   gaps listed in [data-inventory.md](data-inventory.md#open-retention-gaps);
   the Privacy Policy must match its "Retention" and "Account deletion"
   sections.
3. **Images.** Decide GHCR visibility (deploy/README.md, "GHCR visibility and
   cost"); public packages need no `docker login` on the host and no
   `apptainer registry login` on the HPC. Then make sure the first images
   exist **before the cutover**: merge to `master`, wait for the CI and Images
   workflows, and check that `$DC pull` works on the host that will run the
   stack (deploy/README.md, "Images (CI → GHCR)"; without GHCR, build on the
   host as described there).
4. **Staging.** Bring up staging on the Pi (deploy/README.md, "Staging on the
   Pi") and run the smoke test against it from the Pi (see step 7 for what it
   covers):

   ```bash
   export WORKER_API_TOKEN="$(grep '^WORKER_API_TOKEN=' deploy/compose/backend.staging.env | cut -d= -f2-)"
   python3 scripts/smoke_test.py http://<pi-lan-ip>:8080 \
     --otp-command "docker compose -p gaa-staging -f deploy/compose/docker-compose.prod.yml --env-file deploy/compose/compose.staging.env logs --no-log-prefix backend" \
     --i-understand-this-creates-accounts
   ```

   Add `--no-mongo` if staging has no `MONGO_URI`. The script needs only
   Python 3.
5. **Path B only, if the Pi already serves the domain:** lower the DNS TTL
   (for example to 300 s) a day ahead so the switch propagates quickly.

## Launch day

### 1. Domain and DNS

Buy the domain. Point an `A` record (and `AAAA` if the host has IPv6) at the
host that will run Caddy: the Pi's public IP for path A (forward TCP 80 and
443, and UDP 443 for HTTP/3, from the router to the Pi; a home IP can change,
so use a static IP or dynamic DNS), the new server's IP for path B.

Cloudflare is optional. If records are proxied (orange cloud), first add
Cloudflare's ranges and `CF-Connecting-IP` to the Caddyfile (deploy/README.md,
"Behind a CDN"), otherwise every visitor shares Cloudflare's IPs in the per-IP
limits. For the first certificate, "DNS only" (grey cloud) is simplest; switch
to proxied afterwards with SSL mode "Full (strict)".

### 2. Resend

Resend → Domains → Add domain, paste the DNS records it shows (SPF/DKIM, and
optionally the return-path MX), wait for **Verified**. Create an API key with
"Sending access" for that domain. In `deploy/compose/backend.env` set
`EMAIL_BACKEND=resend`, `RESEND_API_KEY`, and
`EMAIL_FROM=Gene Autoannotator <noreply@<domain>>`.

### 3. Atlas access (before any restore)

The backend needs MongoDB for restores and backups, so do this before step 4:

- Network Access: add the host's public IP.
- Database Access: the backend user has `readWrite` on `gene_autoannotator`;
  create the frontend user with a custom role allowing only `find` on
  `gene_autoannotator.annotations` (data-inventory.md, "Mongo users"). Put the
  two URIs in `backend.env` and `frontend.env`.

### 4a. Path A: cut over on the Pi

Use a separate checkout of this branch on the Pi (as for staging), then follow
deploy/README.md from "Env files and preflight" through "Production cutover
from docker-compose.backend.yml". In short:

```bash
cp deploy/compose/backend.prod.env.example deploy/compose/backend.env
cp deploy/compose/frontend.prod.env.example deploy/compose/frontend.env
cp deploy/compose/compose.env.example deploy/compose/compose.env   # SITE_ADDRESS=<domain>
deploy/scripts/preflight-env.sh --role backend deploy/compose/backend.env
deploy/scripts/preflight-env.sh --role frontend deploy/compose/frontend.env
$DC pull
$DC up -d --no-deps caddy && $DC logs caddy | grep -i 'certificate obtained'   # pre-issue the certificate
# cutover (1 to 3 minutes of downtime)
$OLD stop backend frontend
deploy/scripts/migrate-to-prod-compose.sh
$DC up -d        # add -f deploy/compose/docker-compose.worker-port.yml to keep http://<pi>:8000 for running workers
curl -fsS https://<domain>/healthz
```

`$OLD` is the old stack's compose command (deploy/README.md). Rollback:
`$DC stop` then `$OLD start backend frontend`. Continue with step 5.

### 4b. Path B: new server

1. Install Docker Engine with the compose plugin, then check out the repo
   to `/opt/gaa`. The files the stack needs (`docker-compose.prod.yml`,
   `Caddyfile`, `backend.env`, `frontend.env`, `compose.env`) live in
   `/opt/gaa/deploy/compose/`; `server-update.sh` and the compose file's
   relative paths expect that layout:

   ```bash
   # a private repo needs a read-only deploy key or token for the clone
   sudo git clone https://github.com/cadsaltz/gene-autoannotator.git /opt/gaa && cd /opt/gaa
   sudo cp deploy/compose/backend.prod.env.example deploy/compose/backend.env
   sudo cp deploy/compose/frontend.prod.env.example deploy/compose/frontend.env
   sudo cp deploy/compose/compose.env.example deploy/compose/compose.env   # SITE_ADDRESS=<domain>
   # edit all three (copy WORKER_API_TOKEN and the other values from the Pi's backend.env), then:
   sudo deploy/scripts/preflight-env.sh --role backend deploy/compose/backend.env
   sudo deploy/scripts/preflight-env.sh --role frontend deploy/compose/frontend.env
   sudo docker login ghcr.io -u <github-user>   # skip if the packages are public
   sudo $DC pull
   ```

   Run the `$DC` commands below with `sudo` too (or add your user to the
   `docker` group).

2. Take the final backup on the Pi. This needs the Pi to run the new stack
   with `MONGO_URI` (path A done, or at least the prod compose stack started
   there); the old `docker-compose.backend.yml` stack has no backup command,
   see the fallback below. Stop what writes first so nothing is lost:

   ```bash
   # on the Pi, in the checkout the new stack runs from
   $DC stop caddy frontend                                 # site and worker routes down
   $DC exec -u app backend python -m backend.manage backup # prints the snapshot id
   $DC stop backend
   ```

   Keep backups off on anything else sharing the Atlas cluster (staging uses
   `BACKUP_INTERVAL_SECONDS=0`), or `--id latest` could pick its snapshot;
   restoring by the printed id avoids the question.

3. Restore on the server before anyone signs up there. On fresh volumes no
   database exists yet, so no `--force` is needed (`run` goes through the
   entrypoint, so no `-u app`):

   ```bash
   $DC run --rm backend python -m backend.manage list-backups
   $DC run --rm backend python -m backend.manage restore --id <snapshot id>
   $DC up -d
   $DC ps
   ```

   If the backend was already started on the server, restore as in
   deploy/README.md "Moving to another server": `$DC stop backend`, then
   `restore --id <snapshot id> --force`, then `$DC start backend`.

4. Switch DNS to the server if it pointed at the Pi. Caddy obtains the
   certificate once DNS resolves to the server (HTTP-01 on port 80); until
   then `https://<domain>` still reaches the stopped Pi. Check with
   `curl -fsS https://<domain>/healthz`, then sign in and compare user and job
   counts on /admin with the Pi.

**Fallback when the Pi still runs the old stack:** copy the volumes and let
the migration script import them from host directories:

```bash
# on the Pi
OLD="docker compose -f /path/to/old/checkout/deploy/compose/docker-compose.backend.yml"
$OLD stop backend frontend
docker run --rm -v compose_backend-data:/from:ro -v "$PWD":/out alpine tar czf /out/backend-data.tgz -C /from .
docker run --rm -v compose_profiles-data:/from:ro -v "$PWD":/out alpine tar czf /out/profiles-data.tgz -C /from .
scp backend-data.tgz profiles-data.tgz <server>:/tmp/
# on the server, before the first `$DC up -d`
sudo mkdir -p /opt/gaa-import/backend /opt/gaa-import/profiles
sudo tar xzf /tmp/backend-data.tgz -C /opt/gaa-import/backend
sudo tar xzf /tmp/profiles-data.tgz -C /opt/gaa-import/profiles
sudo deploy/scripts/migrate-to-prod-compose.sh --from-backend /opt/gaa-import/backend --from-profiles /opt/gaa-import/profiles
sudo $DC up -d
```

Then switch DNS as in step 4 above. Rollback for path B: point DNS back and
start the Pi's stack again (`$DC start` there, or `$OLD start backend
frontend`); anything created on the server in between stays only there.

### 5. MongoDB redaction and NCBI key rotation

Old annotation documents can contain the NCBI API key inside request URLs,
and the frontend reads those documents directly. Run
`scripts/redact_mongo_secrets.py` with the backend's read-write `MONGO_URI`:
first a dry run, then `--apply` while no jobs are completing (on /admin,
running is 0), then confirm that a second dry run reports 0. The script is not
in the image, so pipe it into the backend container, which has `MONGO_URI`
and pymongo:

```bash
$DC exec -T -u app backend python - < scripts/redact_mongo_secrets.py           # dry run: lists affected ids
$DC exec -T -u app backend python - --apply < scripts/redact_mongo_secrets.py   # rewrites them
$DC exec -T -u app backend python - < scripts/redact_mongo_secrets.py           # must print "0 document(s) contain api_key= values"
```

(From a laptop checkout instead: `MONGO_URI='<read-write URI>' .venv/bin/python
scripts/redact_mongo_secrets.py`, with your IP in Atlas Network Access.)

Then rotate the NCBI API key (data-inventory.md, "Rotation"): new key in
the NCBI account, update `worker.run.env` on the HPC, any `worker.env`, and
`backend.env` if set there, then `$DC up -d --force-recreate backend`.

### 6. HPC

On the HPC login node set `BACKEND_URL=https://<domain>` in `dispatcher.env`
and in the `worker.run.env` that `WORKER_RUN_ENV_FILE` names (path B with an
unchanged domain needs no edit). Check reachability and run one dispatcher
tick by hand once a job is queued (step 7):

```bash
/shared/gene-autoannotator/deploy/scripts/test-backend-reachability.sh https://<domain>
/shared/gene-autoannotator/deploy/scripts/dispatcher-once.sh
```

If the worker-port override was used for path A, drop it (`$DC up -d`) once
running workers have moved to the new URL.

### 7. Smoke checklist

Run the automated part from any machine (codes arrive by email; type them when
asked). `--admin-login` signs the existing admin in without using one of the
per-IP sign-ups; run it from outside the host's network so the audit IP check
means something:

```bash
export WORKER_API_TOKEN=<the production token>
python3 scripts/smoke_test.py https://<domain> --otp-prompt --admin-login \
  --i-understand-this-creates-accounts
```

It checks the legal pages, `robots.txt`, security headers and HSTS, the
`/login` redirect, that the backend's admin API is not exposed at the site
root, `/healthz` and the worker token on the worker routes; admin sign-in (a
Secure, HttpOnly session cookie), the admin overview; a second `+smoke`
account with role `user` that gets 403 on `/admin/*`, `/workers`, `/health`;
annotation search needing a session; queue status without fleet details; a job
submitted by the user and invisible to a third account, claimed by a simulated
worker, progress, and finish; cancel (and a 409 for worker progress on the
cancelled job); a quota 429 with its code; the audit log. It prints the client
IP recorded for its sign-up: behind Caddy that must be your public IP, not a
Docker address. At the end it cancels its jobs, deregisters its worker,
deletes the two accounts, and signs the admin out. It never prints codes,
tokens, or cookies.

On production the simulated worker only claims when its job is the only
queued one, and it **fails** the job rather than completing it, because a
completed job writes a fake annotation into the shared library
(`--complete-with-fake-result` is for deployments without MongoDB). The smoke
jobs stay as anonymized rows (no submitter) and the audit events stay until
`AUDIT_RETENTION_DAYS` (see data-inventory.md, "Account deletion"). Each run uses up to three of the
day's `IP_SIGNUPS_PER_DAY` sign-ups from your IP (two with `--admin-login`).

Then by hand in a browser:

- [ ] Sign in as the bootstrap admin (`solavolantes@gmail.com`): the admin
      console at /admin loads, including Users and Audit.
- [ ] Sign up a second email: its navigation shows only Guide, Jobs,
      Profiles, and Annotations.
- [ ] That user submits a real job; the HPC dispatcher launches a worker
      (step 6), which claims and completes it.
- [ ] The annotation is visible on /annotations.
- [ ] Cancel works on a second job.
- [ ] A quota 429 shows its message (set the user's daily quota low on
      /admin/users).
- [ ] A backup appears in MongoDB about a minute after the backend started:
      `$DC exec -u app backend python -m backend.manage list-backups`.
- [ ] Delete the test account on /admin/users.

### 8. Update cron

Only once the stack runs the way it should stay (worker-port override
dropped, or listed in `GAA_COMPOSE_FILES`), install the cron for root as in
deploy/README.md "Updates":

```cron
*/5 * * * * /opt/gaa/deploy/scripts/server-update.sh
```

(Use the Pi checkout's path for path A.) Check `/var/log/gaa-update.log` after
the first run.
