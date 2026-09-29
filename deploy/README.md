# Deploying Gene Autoannotator

The production stack is `deploy/compose/docker-compose.prod.yml`: prebuilt
backend and frontend images from GHCR plus Caddy, which is the only container
that publishes ports. State lives in named volumes. The older
`docker-compose.backend.yml` (builds from source, publishes 3000 and 8000, one
shared `.env`) stays for LAN/dev use and is what the Raspberry Pi runs today.

| File | Purpose |
|------|---------|
| `compose/docker-compose.prod.yml` | `backend`, `frontend`, `caddy`; volumes `backend-data` (SQLite), `profiles-data`, `caddy-data`, `caddy-config` |
| `compose/Caddyfile` | TLS, routing, `X-Forwarded-For`, HSTS, access logs |
| `compose/docker-compose.worker-port.yml` | Optional: serve worker routes on host port 8000 during the cutover |
| `compose/backend.prod.env.example` → `backend.env` | Backend env (secrets, quotas, alerts, backups) |
| `compose/frontend.prod.env.example` → `frontend.env` | Frontend env (read-only `MONGO_URI`, `BACKEND_API_BASE_URL`) |
| `compose/compose.env.example` → `compose.env` | `IMAGE_TAG`, `SITE_ADDRESS`, host ports, env file names |
| `compose/compose.staging.env.example` → `compose.staging.env` | Staging on the Pi next to the running stack |
| `scripts/preflight-env.sh` | Checks env files; prints names only, never values |
| `scripts/migrate-to-prod-compose.sh` | Copies the old stack's database and profiles into the new volumes |
| `scripts/server-update.sh` | Cron: pull images, recreate what changed, prune dangling images |
| `scripts/test-compose-config.sh` | `docker compose config` + `caddy validate` on the examples |
| `docs/abuse-runbook.md` | Floods, suspensions, limits, token rotation |

The real env files (`deploy/compose/*.env`) are gitignored. Every command
below passes `-p`: the old stack runs as compose project `compose` (the
directory name), and reusing that name would recreate its containers.

```bash
# Production
DC="docker compose -p gaa -f deploy/compose/docker-compose.prod.yml --env-file deploy/compose/compose.env"
# Staging
STG="docker compose -p gaa-staging -f deploy/compose/docker-compose.prod.yml --env-file deploy/compose/compose.staging.env"
```

## Routing and client IPs

Caddy sends these paths straight to `backend:8000`; everything else goes to
`frontend:3000`:

| Path | Caller |
|------|--------|
| `/workers/*` (`register`, `{id}/heartbeat`, `{id}/claim`, `{id}/drain`, `DELETE {id}`) | workers (`worker/client.py`), `update-worker.sh` |
| `/jobs/*/progress`, `/jobs/*/complete`, `/jobs/*/fail` | workers |
| `/jobs/queue-summary` | HPC dispatcher (`dispatcher/loop.py`) |
| `/healthz` | uptime checks, `test-backend-reachability.sh` |

All of them except `/healthz` require the worker token. `*` in the middle of a
Caddy path does not cross `/`, so the `/jobs` page, `/jobs?...`,
`/jobs/<id>`, `/jobs/<id>/result`, `/workers` (admin list), `/admin/*`, and
`/auth/*` never reach the backend directly; browsers use the frontend's
same-origin `/api/backend/*` proxy. `tests/test_deploy_compose.py` derives the
worker, dispatcher, and script paths from the code and fails if one is not
routed, if a frontend page is, or if an exposed backend route lacks the token
check.

Workers must use `BACKEND_URL=https://<domain>` for a hostname site: Caddy
redirects plain HTTP with a 308 and the worker client does not follow
redirects.

Client IP chain, which the per-IP limits (`TRUST_FORWARDED_FOR=1`) depend on:

- Browser → Caddy → frontend → backend: Caddy replaces `X-Forwarded-For` with
  the connecting IP (`header_up X-Forwarded-For {client_ip}`), Next keeps it,
  and the `/api/backend` proxy forwards it (`frontend/lib/backendProxy.js`).
- Worker → Caddy → backend: same header, one hop.
- Backend and frontend publish no ports, so nothing reaches them without Caddy.

**Behind a CDN (e.g. Cloudflare proxied DNS)** every request arrives from the
CDN's IPs. Add its ranges and client-IP header to the Caddyfile's global
options, and `{client_ip}` becomes the visitor's IP:

```caddy
{
	servers {
		trusted_proxies static 173.245.48.0/20 103.21.244.0/22 # ... the full list from cloudflare.com/ips
		client_ip_headers CF-Connecting-IP
	}
}
```

Only list the CDN's own ranges: any listed IP can set its own client IP.

Other Caddy behaviour: HSTS (`max-age=31536000`) only on HTTPS responses, so
never for `SITE_ADDRESS=:80`; `encode zstd gzip`; JSON access logs on stdout
(`Authorization` and `Cookie` are redacted by Caddy); request bodies capped at
10 MB for the frontend and 32 MB for worker routes (job results are tens of KB;
the largest seen locally is 36 KB). Containers keep at most 5 × 10 MB of logs.
After editing the Caddyfile: `$DC exec caddy caddy reload --config /etc/caddy/Caddyfile`.

## Env files and preflight

```bash
cp deploy/compose/backend.prod.env.example deploy/compose/backend.env
cp deploy/compose/frontend.prod.env.example deploy/compose/frontend.env
cp deploy/compose/compose.env.example deploy/compose/compose.env
# edit all three, then:
deploy/scripts/preflight-env.sh --role backend deploy/compose/backend.env
deploy/scripts/preflight-env.sh --role frontend deploy/compose/frontend.env
deploy/scripts/test-compose-config.sh
```

Preflight prints `OK`, `MISSING`, `PLACEHOLDER` (still `CHANGE_ME`), or
`INVALID` per name and exits non-zero on any problem. The backend role also
requires `REQUIRE_WORKER_API_TOKEN=1` and `TRUST_FORWARDED_FOR=1`, which are
right for every deployment behind this Caddyfile. Without `--role` it checks
the old stack's shared `.env`.

## Images (CI → GHCR)

`.github/workflows/ci.yml` runs on every push and pull request: the tracked
Python tests with the backend image's pinned dependencies (no torch/CUDA
stack), and `npm ci`, `npm test`, `npm run lint`, `npm run build` in
`frontend/` (no env secrets needed). Five `tests/test_gene_names.py`
annotation-table tests that already fail on master are deselected there.

`.github/workflows/images.yml` runs after each successful CI run of a push to
`master`, builds the exact commit CI tested, and pushes:

| Image | Platforms | Tags |
|-------|-----------|------|
| `ghcr.io/cadsaltz/gene-autoannotator-backend` | amd64, arm64 | `sha-<7-char sha>`, `prod` |
| `ghcr.io/cadsaltz/gene-autoannotator-frontend` | amd64, arm64 | `sha-<7-char sha>`, `prod` |
| `ghcr.io/cadsaltz/gene-autoannotator-worker` | amd64 | `sha-<7-char sha>`, `prod` (plus `buildcache`) |

`prod` moves only after all three images built, and only if the commit is
still the tip of `master` (a newer push promotes itself). The arm64 frontend
build runs under QEMU and takes the longest (expect 15 to 30 minutes per
run). The workflow only fires once it is on the default branch; **Run
workflow** on the Actions tab (`workflow_dispatch`) builds any branch with
just the `sha-` tag, e.g. for staging.

GHCR packages start private. The host that pulls them logs in once with a
classic personal access token that has only `read:packages`, as the user
that runs `server-update.sh` (root, for the cron below):

```bash
sudo docker login ghcr.io -u <github-user>   # paste the token as the password
```

`IMAGE_TAG` in `compose.env` picks the tag: `prod` (default, follows master),
`sha-<7-char sha>` to pin a commit, or `previous` (see Updates).

**Before the cutover the images must exist in GHCR**: push to `master`, wait
for CI and then Images to finish, then `$DC pull`. Fallback without GHCR:
build on the Pi from the checkout you deploy, tagged the way the compose file
expects (native arm64, no QEMU):

```bash
docker build -f deploy/docker/Dockerfile.backend  -t ghcr.io/cadsaltz/gene-autoannotator-backend:prod .
docker build -f deploy/docker/Dockerfile.frontend -t ghcr.io/cadsaltz/gene-autoannotator-frontend:prod .
```

and leave the update cron off until GHCR has the images: `pull` fails
without them (or without the login), and once they exist it replaces the
local `:prod` images.

## Staging on the Pi (no domain, old stack keeps running)

The running `docker-compose.backend.yml` stack keeps ports 3000 and 8000 and
its volumes. Staging is a separate project (`gaa-staging`) with its own
containers and volumes, and Caddy on host ports 8080/8443.

1. Use a separate checkout of this branch so the running stack's checkout is
   untouched, e.g. `git clone <repo> ~/gaa-next && cd ~/gaa-next && git checkout feat/go-public-d-g`.
2. Build arm64 images locally (until CI publishes them). The old containers
   keep serving meanwhile:

   ```bash
   docker build -f deploy/docker/Dockerfile.backend -t ghcr.io/cadsaltz/gene-autoannotator-backend:staging .
   docker build -f deploy/docker/Dockerfile.frontend -t ghcr.io/cadsaltz/gene-autoannotator-frontend:staging .
   ```

3. Env files:

   ```bash
   cd deploy/compose
   cp compose.staging.env.example compose.staging.env
   cp backend.prod.env.example backend.staging.env
   cp frontend.prod.env.example frontend.staging.env
   cd ../..
   ```

   In `backend.staging.env` apply the "Staging overrides" block at its end:
   `SESSION_COOKIE_SECURE=0`, `EMAIL_BACKEND=console`,
   `BACKUP_INTERVAL_SECONDS=0`, `BACKEND_PUBLIC_URL=http://<pi-lan-ip>:8080`,
   and fill in `WORKER_API_TOKEN` and `MONGO_URI`. Keep backups off in
   staging: its snapshots would land in the production GridFS bucket, and
   `restore --id latest` could later pick one.

   **MongoDB is shared unless you separate it.** The database name is
   hardcoded (`gene_autoannotator` in `backend/annotation_store.py` and
   `frontend/lib/annotationStore.js`; there is no env override), so a staging
   `MONGO_URI` for the production cluster reads and writes the production
   annotation library: every job completed on staging lands there. A separate
   Atlas user alone does not help. Use a separate cluster for staging (a free
   M0 in its own Atlas project, or a throwaway `mongo` container) in both
   `backend.staging.env` and `frontend.staging.env`, or accept that staging
   test annotations appear in production.
4. Optional, to test with real accounts, jobs, and profiles: seed staging from
   the running stack without stopping it (SQLite online backup; the source is
   only read):

   ```bash
   deploy/scripts/migrate-to-prod-compose.sh --online --to-project gaa-staging \
     --image ghcr.io/cadsaltz/gene-autoannotator-backend:staging
   ```

   Without it staging starts empty. The bootstrap admin
   (`solavolantes@gmail.com`) becomes admin when that account signs up.
5. Start and test:

   ```bash
   $STG up -d
   $STG ps                                   # all three running, backend/frontend healthy
   curl -fsS http://<pi-lan-ip>:8080/healthz
   $STG logs backend | grep email:console    # sign-in codes
   ```

   Open `http://<pi-lan-ip>:8080`, sign in as the bootstrap admin and as a
   second email, and walk the smoke checklist in the launch runbook. Browsers
   share cookies across ports of one host, so use a private window if you are
   also signed in to the old UI on port 3000. Jobs only run if a worker uses
   `BACKEND_URL=http://<pi-lan-ip>:8080`; the HPC dispatcher still points at
   the old backend.
6. Stop with `$STG down` (keeps volumes) or `$STG down -v` (deletes staging
   data). Do not install the update cron for staging: `IMAGE_TAG=staging`
   exists only locally, so `pull` fails.

## Production cutover from docker-compose.backend.yml

New named volumes would start with an empty database and no profiles, so the
cutover copies the old volumes (`compose_backend-data`, which holds
`jobs.sqlite3`, and `compose_profiles-data`) into `gaa_backend-data` and
`gaa_profiles-data`. The old volumes are mounted read-only and never changed,
which is what makes rollback safe. Schema migrations run when the new backend
first opens the copy.

Preparation (no downtime):

1. Staging passed. Env files for production exist and pass preflight.
   `SITE_ADDRESS` is the hostname, DNS points at the host, ports 80/443 are
   reachable (Caddy needs port 80 for the first certificate).
2. Images are on the host: `$DC pull` (needs the GHCR images and login, see
   Images), or locally built and tagged with `IMAGE_TAG`.
3. `docker compose ls` shows the old project name (normally `compose`); pass
   `--from-project` below if it differs. Point `OLD` at the checkout the old
   stack was started from, and note its state:

   ```bash
   OLD="docker compose -f /path/to/old/checkout/deploy/compose/docker-compose.backend.yml"
   $OLD ps
   ```

4. Pre-issue the certificate so it isn't part of the downtime. Check that
   nothing else listens on 80/443 (`ss -ltn '( sport = :80 or sport = :443 )'`
   prints only the header), then start Caddy alone:

   ```bash
   $DC up -d --no-deps caddy
   $DC logs caddy | grep -i 'certificate obtained'
   ```

   Until the cutover the site answers 502 (no backend or frontend yet), and
   the update cron (if installed) skips because the backend is not running.
   If 80/443 are taken, skip this; the first request after `up -d` then waits
   for issuance (seconds to about a minute).
5. Don't install the update cron yet (see Updates).
6. Pick a quiet moment: check /fleet for running jobs.

Cutover (estimated downtime 1 to 3 minutes):

```bash
$OLD stop backend frontend                               # downtime starts; containers kept for rollback
deploy/scripts/migrate-to-prod-compose.sh                # seconds for a DB of a few MB; prints row counts
$DC up -d                                                # add -f deploy/compose/docker-compose.worker-port.yml, see below
$DC ps && curl -fsS https://<domain>/healthz             # downtime ends when this answers
```

Then sign in, check /admin, and compare the user and job counts with the
migration output.

Workers and the dispatcher: point `BACKEND_URL` in `dispatcher.env` and the
worker env files at `https://<domain>`. Slurm workers already running keep
their old URL; their `complete`/`fail` calls retry for 5 minutes, then the job
is requeued when its lease expires. To keep them working without an edit,
start the stack with the worker-port override:

```bash
docker compose -p gaa -f deploy/compose/docker-compose.prod.yml \
  -f deploy/compose/docker-compose.worker-port.yml --env-file deploy/compose/compose.env up -d
```

Caddy then serves only the worker routes and `/healthz` on host port 8000
over plain HTTP (the same exposure as today's backend port), so
`http://<host>:8000` keeps working. Move `BACKEND_URL` to `https://<domain>`,
then drop the override (`$DC up -d`) once running workers have cycled.

Rollback (the old volumes are exactly as they were at cutover). If the update
cron is installed, comment it out first; it skips a stopped stack, but you
don't want it running while you switch back and forth:

```bash
$DC stop                  # frees 80/443 (and 8000 if the override was used)
$OLD start backend frontend
```

`start` reuses the stopped old containers, images, and config. Do not use
`up` or `up --build` to roll back: that recreates the containers from
whatever code and compose file the checkout has now.
Accounts or jobs created on the new stack after cutover are only in
`gaa_backend-data`. Revert `BACKEND_URL` on the HPC if you changed it.
Delete the old containers and volumes only after the new stack has run well
for a while.

Re-running the migration refuses if the target volumes are not empty; pass
`--force` to move their contents into `.pre-migrate-<timestamp>/` inside the
volume (nothing is deleted). Sources can also be given explicitly as volume
names or absolute host directories: `--from-backend`, `--from-profiles`. For a
host directory the script cannot tell whether a backend still uses it and
only warns, so stop the old backend yourself. `--online` into the production
project `gaa` is refused (writes after the copy would be lost) unless you add
`--i-know-writes-are-lost`.

### Moving to another server

Once the new stack runs anywhere with `MONGO_URI`, it snapshots SQLite and
profiles to MongoDB every `BACKUP_INTERVAL_SECONDS`. On the new server:
`$DC up -d`, `$DC stop backend`, `$DC run --rm backend python -m backend.manage restore --id latest --force`,
`$DC start backend` (see `backend/README.md` § Backups and restore).

## Updates

`deploy/scripts/server-update.sh`, each run:

1. Takes an `flock` (`/run/lock/gaa-update.lock`, else `/tmp`); an
   overlapping run exits.
2. Exits with `stack not running; skipping` unless the project's backend is
   running, so it never starts a stack you stopped (before cutover, during a
   rollback, while only Caddy runs to pre-issue the certificate).
3. Runs preflight on both env files (an absolute `BACKEND_ENV_FILE` works);
   a failure leaves the running stack alone.
4. `docker compose pull` and `up -d`: only containers whose image changed are
   recreated. It logs the image IDs before and after, and tags the
   pre-update backend and frontend images `:previous`.
5. Waits up to 90 s for the backend's `/healthz`; if it does not answer it
   logs `ERROR: backend is not healthy ...` with the rollback command (it does
   not roll back by itself). Otherwise `docker image prune -f` (dangling
   images only; `:previous` stays).

It logs to `/var/log/gaa-update.log`. Install for root (Docker access and the
log path) only once the stack runs the way it should stay:

```cron
*/5 * * * * /path/to/checkout/deploy/scripts/server-update.sh
```

**Pass every compose file the stack was started with.** The cron runs
`up -d` with its own `-f` list; with only the prod file it would drop the
worker-port override within five minutes. Either install the cron after the
override is dropped, or list both files:

```cron
*/5 * * * * GAA_COMPOSE_FILES=/path/to/checkout/deploy/compose/docker-compose.prod.yml:/path/to/checkout/deploy/compose/docker-compose.worker-port.yml /path/to/checkout/deploy/scripts/server-update.sh
```

Other overrides: `GAA_PROJECT`, `GAA_ENV_FILE`, `GAA_UPDATE_LOG`,
`GAA_UPDATE_LOCK`, `GAA_HEALTH_TIMEOUT`. It does not `git pull`; compose file
or Caddyfile changes need a manual `git pull` and `$DC up -d` (plus a Caddy
reload for the Caddyfile). Add a logrotate rule for the log if it grows.

Rolling back a bad image update:

1. Comment out the cron line (otherwise the next run pulls `prod` again).
2. In `compose.env` set `IMAGE_TAG=previous` (the pair that ran before the
   last update, tagged locally by the script), or `IMAGE_TAG=sha-<shortsha>`
   of a known-good commit from GHCR.
3. `$DC up -d`, check `/healthz` and a login.
4. After `prod` is fixed, set `IMAGE_TAG=prod` again and re-enable the cron.

`:previous` only covers the most recent update; the log keeps the image IDs of
every update (`docker image inspect <id>` shows its digest if the image is
still present).

## HPC updates (dispatcher checkout and worker SIF)

The HPC side runs from a git checkout on the shared filesystem: the
dispatcher (`dispatcher-once.sh`, scrontab) uses the checkout's `.venv`, and
each Slurm worker-run starts the SIF named by `WORKER_IMAGE` in
`dispatcher.env`. `deploy/scripts/hpc-update.sh` keeps both on the same
commit:

1. `flock` on `<repo>/.hpc-update.lock`; an overlapping run exits.
2. `git fetch`, then `apptainer pull` of
   `ghcr.io/cadsaltz/gene-autoannotator-worker:sha-<7-char sha>` for the
   upstream tip into `<repo>/sif/worker-sha-<sha>.sif` (skipped if present).
   If that image isn't there yet (Images still running, CI failed, no
   registry login) it logs `waiting: ...` and changes nothing.
3. `git merge --ff-only`. A diverged checkout or local edits that conflict
   with the update stop the run with an error in the log.
4. Reinstalls `requirements.txt` and `requirements-web.txt` into `.venv` when
   their contents changed since the last install.
5. Points `sif/worker-current.sif` at the new SIF (running allocations keep
   the file they opened; pending ones get the new one) and deletes older SIFs,
   keeping the two newest and any whose replacement is under 48 hours old.

It logs to `<repo>/hpc-update.log`. One-time setup on the login node:

```bash
# read:packages token, as for the Pi (skip if the packages are made public)
apptainer registry login --username <github-user> docker://ghcr.io
# dispatcher.env
WORKER_IMAGE=/shared/gene-autoannotator/sif/worker-current.sif
# first run by hand, then check the log
/shared/gene-autoannotator/deploy/scripts/hpc-update.sh; tail /shared/gene-autoannotator/hpc-update.log
```

scrontab (`scrontab -e`); scrontab entries run as Slurm jobs, so the node
they land on needs outbound HTTPS to GitHub and ghcr.io, and converting the image to a SIF needs
a few CPUs, memory, and roughly twice the image size (about 15 GB) of scratch
under `sif/.tmp`:

```cron
#SCRON --time=02:00:00 --cpus-per-task=4 --mem=16G
17 4 * * * /shared/gene-autoannotator/deploy/scripts/hpc-update.sh
```

A run with nothing new only fetches, so it can run more often than daily.
Overrides: `GAA_SIF_DIR`, `GAA_VENV`, `GAA_REQUIREMENTS`, `GAA_SIF_KEEP`,
`GAA_SIF_GRACE_HOURS`, `GAA_HPC_UPDATE_LOG`, `GAA_HPC_UPDATE_LOCK`,
`APPTAINER` (e.g. `singularity`), `APPTAINER_TMPDIR`. With a hand-built SIF,
`GAA_PULL_SIF=0` updates only the code and venv. To roll back, set
`WORKER_IMAGE` to a kept `worker-sha-*.sif` and comment out the scrontab line
(the next run would move `worker-current.sif` again, but not `WORKER_IMAGE`).

## Operations

```bash
$DC logs -f backend
$DC exec -u app backend python -m backend.manage list-users
$DC exec -u app backend python -m backend.manage set-role EMAIL admin
$DC exec -u app backend python -m backend.manage backup
```

`exec` starts in the image's `WORKDIR /state` with `PYTHONPATH=/app`, so the
relative database path `backend/jobs.sqlite3` resolves to the
`backend-data` volume. Pass `-u app`: `exec` bypasses the entrypoint and would
otherwise run as root. `$DC run --rm backend ...` goes through the entrypoint
and needs no flag. After editing `backend.env`, `$DC up -d` recreates the
backend (`restart` does not re-read env files). See `docs/abuse-runbook.md`
for incident steps.
