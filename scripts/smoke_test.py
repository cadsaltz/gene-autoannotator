#!/usr/bin/env python3
"""End-to-end smoke test for a running Gene Autoannotator deployment.

Walks the launch checklist over HTTP: bootstrap admin sign-in, a second
account, role and tenancy checks, a job submitted by the second account and
handled by a simulated worker, cancel, a quota 429, legal pages, robots.txt,
and security headers. Browser calls go through the site's same-origin
``/api/backend`` proxy (so cookies, the Next proxy, and X-Forwarded-For are
exercised); worker calls use the worker routes with ``WORKER_API_TOKEN``.

Standard library only; run it from any machine that reaches the site.

It creates real accounts, so it refuses to run without
``--i-understand-this-creates-accounts``. Test accounts are ``+smoke``
aliases of the admin address and are deleted at the end (checking that the
deletion anonymizes their jobs and masks the email in the audit log); smoke
jobs are cancelled. The admin account is only signed in (and signed out at
the end).
Sign-in codes, the worker token, and session cookies are never printed.

The simulated worker only claims when the smoke job is the only queued job,
and by default it *fails* the job instead of completing it: a completed job
is written to the MongoDB annotation library (as the current annotation of
the target gene) when the backend has ``MONGO_URI``. Pass
``--complete-with-fake-result`` only for a deployment without MongoDB or
with a throwaway one.

Examples::

    # Pi staging (run on the Pi; sign-in codes come from the console email log)
    export WORKER_API_TOKEN="$(grep '^WORKER_API_TOKEN=' deploy/compose/backend.staging.env | cut -d= -f2-)"
    python3 scripts/smoke_test.py http://<pi-lan-ip>:8080 \\
      --otp-command "docker compose -p gaa-staging -f deploy/compose/docker-compose.prod.yml \\
        --env-file deploy/compose/compose.staging.env logs --no-log-prefix backend" \\
      --i-understand-this-creates-accounts

    # Production (codes arrive by email; type them when asked)
    python3 scripts/smoke_test.py https://<domain> --otp-prompt --admin-login \\
      --i-understand-this-creates-accounts

    # Local uvicorn + next start (see deploy/docs/launch-runbook.md)
    python3 scripts/smoke_test.py http://127.0.0.1:3000 --worker-url http://127.0.0.1:8000 \\
      --otp-log-file /tmp/backend.log --complete-with-fake-result --no-mongo \\
      --i-understand-this-creates-accounts

Exit status: 0 when every check passed or was skipped, 1 on any failure,
2 on bad arguments.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

BOOTSTRAP_ADMIN_EMAIL = "solavolantes@gmail.com"
SESSION_COOKIE = "ga_session"
OTP_LINE = re.compile(r"\[email:console\] to=(\S+) code=(\d{6})")
LEGAL_PAGES = ("terms", "privacy", "acceptable-use", "disclaimer")
FLEET_KEYS = ("worker", "slot", "connected", "fleet", "hostname")


class SmokeAbort(Exception):
    """A check failed that later steps depend on."""


class Response:
    def __init__(self, status, headers, body):
        self.status = status
        self.headers = headers
        self.body = body

    def header(self, name):
        return self.headers.get(name)

    def header_all(self, name):
        return self.headers.get_all(name) or []

    def json(self):
        try:
            return json.loads(self.body.decode("utf-8") or "null")
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None

    def detail(self):
        data = self.json()
        if isinstance(data, dict):
            return str({key: data[key] for key in ("detail", "code") if key in data})[:300]
        return self.body[:200].decode("utf-8", "replace")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def http(method, url, *, json_body=None, headers=None, timeout=30):
    data = None
    request_headers = {"Accept": "application/json", "User-Agent": "gaa-smoke-test"}
    request_headers.update(headers or {})
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=method, headers=request_headers)
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            return Response(response.status, response.headers, response.read())
    except urllib.error.HTTPError as exc:
        return Response(exc.code, exc.headers, exc.read())


class Session:
    """One browser: calls /api/backend/* on the site with its own session cookie."""

    def __init__(self, base_url, label):
        self.base_url = base_url
        self.label = label
        self.cookie = None
        self.user = None

    def call(self, method, path, json_body=None):
        headers = {"Cookie": f"{SESSION_COOKIE}={self.cookie}"} if self.cookie else {}
        return http(method, f"{self.base_url}/api/backend{path}", json_body=json_body, headers=headers)


class Worker:
    def __init__(self, worker_url, token):
        self.worker_url = worker_url
        self.token = token
        self.worker_id = None

    def call(self, method, path, json_body=None, *, auth=True):
        headers = {"Authorization": f"Bearer {self.token}"} if auth and self.token else {}
        return http(method, f"{self.worker_url}{path}", json_body=json_body, headers=headers)


class OtpSource:
    def __init__(self, *, log_file=None, command=None, prompt=False, timeout=30):
        self.log_file = Path(log_file) if log_file else None
        self.command = command
        self.prompt = prompt
        self.timeout = timeout

    def _text(self):
        if self.log_file is not None:
            try:
                return self.log_file.read_text(encoding="utf-8", errors="replace")
            except FileNotFoundError:
                return ""
        result = subprocess.run(
            self.command, shell=True, capture_output=True, text=True, timeout=60
        )
        return result.stdout + result.stderr

    def _codes(self, email):
        return [
            code
            for to, code in OTP_LINE.findall(self._text())
            if to.strip().lower() == email.lower()
        ]

    def mark(self, email):
        return 0 if self.prompt else len(self._codes(email))

    def wait(self, email, seen):
        if self.prompt:
            return getpass.getpass(f"  Sign-in code sent to {email} (input hidden): ").strip()
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            codes = self._codes(email)
            if len(codes) > seen:
                return codes[-1]
            time.sleep(1)
        raise SmokeAbort(f"no new sign-in code for {email} within {self.timeout}s")


class Smoke:
    def __init__(self, args):
        self.args = args
        self.base = args.base_url.rstrip("/")
        self.worker_url = (args.worker_url or args.base_url).rstrip("/")
        self.https = self.base.startswith("https://")
        self.otp = OtpSource(
            log_file=args.otp_log_file,
            command=args.otp_command,
            prompt=args.otp_prompt,
            timeout=args.otp_timeout,
        )
        stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        local, _, domain = args.admin_email.partition("@")
        local = local.split("+", 1)[0]
        self.user_email = f"{local}+smoke-{stamp}@{domain}"
        self.other_email = f"{local}+smoke-{stamp}-other@{domain}"
        self.admin = Session(self.base, "admin")
        self.user = Session(self.base, "user")
        self.other = Session(self.base, "other user")
        self.worker = Worker(self.worker_url, args.worker_token)
        self.job_ids = []
        self.results = {"PASS": 0, "FAIL": 0, "SKIP": 0}

    # -- reporting ---------------------------------------------------------

    def report(self, outcome, name, detail=""):
        self.results[outcome] += 1
        suffix = f": {detail}" if detail else ""
        print(f"{outcome:4} {name}{suffix}", flush=True)

    def check(self, name, ok, detail="", *, critical=False):
        self.report("PASS" if ok else "FAIL", name, "" if ok else detail)
        if not ok and critical:
            raise SmokeAbort(name)
        return ok

    def expect(self, name, response, status, *, critical=False):
        statuses = status if isinstance(status, tuple) else (status,)
        return self.check(
            name,
            response.status in statuses,
            f"HTTP {response.status} (expected {'/'.join(map(str, statuses))}) {response.detail()}",
            critical=critical,
        )

    def skip(self, name, reason):
        self.report("SKIP", name, reason)

    def info(self, message):
        print(f"INFO {message}", flush=True)

    # -- steps -------------------------------------------------------------

    def public_pages(self):
        response = http("GET", f"{self.base}/robots.txt", headers={"Accept": "text/plain"})
        text = response.body.decode("utf-8", "replace")
        self.check(
            "robots.txt served and disallows /admin and /api/",
            response.status == 200 and "Disallow: /admin" in text and "Disallow: /api/" in text,
            f"HTTP {response.status}",
        )
        for page in LEGAL_PAGES:
            response = http("GET", f"{self.base}/legal/{page}", headers={"Accept": "text/html"})
            self.expect(f"/legal/{page} renders without a session", response, 200)
        home = http("GET", f"{self.base}/", headers={"Accept": "text/html"})
        self.expect("homepage renders", home, 200)
        expected = {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "strict-origin-when-cross-origin",
        }
        for name, value in expected.items():
            actual = home.header(name) or ""
            self.check(f"security header {name}", actual == value, f"got {actual!r}")
        csp = home.header("Content-Security-Policy") or ""
        self.check(
            "Content-Security-Policy set (production build)",
            "frame-ancestors 'none'" in csp and "connect-src 'self'" in csp,
            f"got {csp[:80]!r}",
        )
        hsts = home.header("Strict-Transport-Security")
        if self.https:
            self.check("HSTS on HTTPS", bool(hsts and "max-age=" in hsts), f"got {hsts!r}")
        else:
            self.check("no HSTS over plain HTTP", hsts is None, f"got {hsts!r}")
        response = http("GET", f"{self.base}/jobs", headers={"Accept": "text/html"})
        location = response.header("Location") or ""
        self.check(
            "protected page redirects to /login without a session",
            response.status in (302, 303, 307, 308) and "/login" in location,
            f"HTTP {response.status} Location={location!r}",
        )
        response = http("GET", f"{self.base}/admin/users")
        self.check(
            "backend admin API not reachable at the site root",
            "application/json" not in (response.header("Content-Type") or ""),
            f"HTTP {response.status} returned JSON",
        )

    def worker_routes(self):
        response = http("GET", f"{self.worker_url}/healthz")
        self.check(
            "/healthz on the worker URL",
            response.status == 200 and (response.json() or {}).get("status") == "ok",
            f"HTTP {response.status}",
        )
        if not self.args.simulate_worker:
            return
        response = self.worker.call("GET", "/jobs/queue-summary", auth=False)
        self.expect("worker route rejects a missing token", response, 401)
        response = self.worker.call("GET", "/jobs/queue-summary")
        self.check(
            "dispatcher queue-summary with token",
            response.status == 200 and isinstance((response.json() or {}).get("queued"), int),
            f"HTTP {response.status} {response.detail()}",
            critical=True,
        )

    def sign_in(self, session, email, *, signup=True, try_wrong_code=False):
        endpoint = "/auth/signup" if signup else "/auth/login"
        body = {"email": email, "accept_terms": True} if signup else {"email": email}
        seen = self.otp.mark(email)
        response = session.call("POST", endpoint, body)
        self.expect(f"{session.label}: POST {endpoint}", response, 200, critical=True)
        code = self.otp.wait(email, seen)
        if try_wrong_code:
            wrong = f"{(int(code) + 1) % 1000000:06d}" if code.isdigit() else "000000"
            response = session.call("POST", "/auth/verify", {"email": email, "code": wrong})
            self.expect(f"{session.label}: wrong sign-in code is rejected", response, 401)
        response = session.call("POST", "/auth/verify", {"email": email, "code": code})
        self.expect(f"{session.label}: verify sign-in code", response, 200, critical=True)
        cookie_header = next(
            (value for value in response.header_all("Set-Cookie") if value.startswith(f"{SESSION_COOKIE}=")),
            "",
        )
        session.cookie = cookie_header.split(";", 1)[0].partition("=")[2] or None
        attributes = cookie_header.lower()
        self.check(f"{session.label}: session cookie issued", bool(session.cookie), critical=True)
        self.check(
            f"{session.label}: cookie is HttpOnly and SameSite=Lax",
            "httponly" in attributes and "samesite=lax" in attributes,
            "missing HttpOnly or SameSite=Lax",
        )
        if self.https:
            self.check(f"{session.label}: cookie is Secure", "secure" in attributes, "SESSION_COOKIE_SECURE is off")
        response = session.call("GET", "/auth/me")
        self.expect(f"{session.label}: /auth/me", response, 200, critical=True)
        session.user = response.json()

    def admin_checks(self):
        response = self.admin.call("POST", "/auth/signup", {"email": self.user_email})
        self.expect("signup without accept_terms is rejected", response, 422)
        self.sign_in(self.admin, self.args.admin_email, signup=not self.args.admin_login)
        self.check(
            "bootstrap admin has role admin",
            self.admin.user.get("role") == "admin",
            f"role={self.admin.user.get('role')!r}",
            critical=True,
        )
        response = self.admin.call("GET", "/admin/overview")
        data = response.json() or {}
        self.check(
            "admin overview loads",
            response.status == 200 and "queued" in data and "users_total" in data,
            f"HTTP {response.status} {response.detail()}",
        )
        if response.status == 200:
            self.info(
                f"overview: queued={data.get('queued')} running={data.get('running')} "
                f"workers_online={data.get('workers_online')} version={data.get('version')}"
            )
        self.expect("admin can list workers", self.admin.call("GET", "/workers"), 200)

    def user_checks(self):
        self.sign_in(self.user, self.user_email, try_wrong_code=True)
        self.check(
            "second account has role user",
            self.user.user.get("role") == "user",
            f"role={self.user.user.get('role')!r}",
            critical=True,
        )
        for method, path in (
            ("GET", "/admin/overview"),
            ("GET", "/admin/users"),
            ("GET", "/admin/audit"),
            ("GET", "/workers"),
            ("GET", "/health"),
            ("GET", "/backend-info"),
        ):
            self.expect(f"user gets 403 on {method} {path}", self.user.call(method, path), 403)
        search = f"{self.base}/api/annotations/search?query={urllib.parse.quote(self.args.locus)}"
        response = http("GET", search)
        self.expect("annotation search needs a session", response, 401)
        response = http("GET", search, headers={"Cookie": f"{SESSION_COOKIE}={self.user.cookie}"})
        if self.args.no_mongo and response.status == 503:
            self.skip("user can query the annotation library", "--no-mongo and the frontend has no MongoDB")
        else:
            self.expect("user can query the annotation library", response, 200)
        response = self.user.call("GET", "/jobs/queue-status")
        data = response.json() or {}
        self.check(
            "user queue-status has a queued count",
            response.status == 200 and isinstance(data.get("queued"), int),
            f"HTTP {response.status} {response.detail()}",
        )
        leaked = [key for key in data if any(word in key.lower() for word in FLEET_KEYS)]
        self.check("user queue-status reveals no fleet info", not leaked, f"keys {leaked}")

    def submit(self, session, name):
        response = session.call("POST", "/jobs", {"profile": self.args.profile, "locus": self.args.locus})
        job_id = (response.json() or {}).get("job_id")
        if response.status == 201 and job_id:
            self.job_ids.append(job_id)
        self.expect(name, response, 201)
        return job_id if response.status == 201 else None

    def register_worker(self):
        payload = {
            "worker_name": f"smoke-test-{os.getpid()}",
            "hostname": "smoke-test",
            "agent_version": "smoke-test",
            "total_memory_bytes": 0,
            "dedicated_memory_bytes": 0,
            "max_slots": 1,
        }
        response = self.worker.call("POST", "/workers/register", payload, auth=False)
        self.expect("worker register rejects a missing token", response, 401)
        response = self.worker.call("POST", "/workers/register", payload)
        self.expect("simulated worker registers", response, 200, critical=True)
        self.worker.worker_id = (response.json() or {}).get("worker_id")
        self.heartbeat()

    def heartbeat(self, active=0):
        response = self.worker.call(
            "POST",
            f"/workers/{self.worker.worker_id}/heartbeat",
            {"active_jobs": active, "free_slots": 1 - active, "memory_available_bytes": 0, "state": "ready"},
        )
        self.expect("simulated worker heartbeat", response, 200)

    def only_queued_job_is(self, job_id):
        response = self.admin.call("GET", "/jobs?order=queue")
        jobs = (response.json() or {}).get("jobs") or []
        queued = [job["id"] for job in jobs if job.get("status") == "queued"]
        return response.status == 200 and queued == [job_id]

    def claim(self, job_id):
        """Claim `job_id`; returns True only if the worker now holds it."""
        if not self.only_queued_job_is(job_id):
            self.skip("simulated worker claims the smoke job", "other jobs are queued; not claiming real work")
            return False
        response = self.worker.call("POST", f"/workers/{self.worker.worker_id}/claim", {"free_slots": 1})
        claimed = (response.json() or {}).get("job_id") if response.status == 200 else None
        if claimed and claimed != job_id:
            self.worker.call(
                "POST",
                f"/jobs/{claimed}/fail",
                {"error": "smoke test claimed this job by mistake; requeued", "retryable": True,
                 "worker_id": self.worker.worker_id},
            )
            self.check("simulated worker claims the smoke job", False, "claimed another job; released it (retryable)")
            return False
        if claimed is None:
            self.skip("simulated worker claims the smoke job", f"HTTP {response.status}: a real worker may have taken it")
            return False
        self.check("simulated worker claims the smoke job", True)
        self.heartbeat(active=1)
        return True

    def job_status(self, session, job_id):
        response = session.call("GET", f"/jobs/{job_id}")
        return response.status, (response.json() or {})

    def job_flow(self):
        if self.args.simulate_worker:
            # Before submitting, so WORKER_CAPACITY_REQUIRED=1 sees a ready worker.
            self.register_worker()
        job_id = self.submit(self.user, "user submits a job")
        if not job_id:
            raise SmokeAbort("job submission failed")
        response = self.user.call("GET", "/jobs/queue-status")
        data = response.json() or {}
        self.check(
            "queue-status counts the new job",
            data.get("queued", 0) >= 1 and data.get("your_active", 0) >= 1,
            f"queued={data.get('queued')} your_active={data.get('your_active')}",
        )
        response = self.user.call("GET", "/jobs")
        jobs = (response.json() or {}).get("jobs") or []
        own = next((job for job in jobs if job.get("id") == job_id), None)
        self.check("owner sees the job in /jobs", own is not None, "missing")
        self.check(
            "owner's job list has no submitter fields",
            own is not None and "submitted_by_email" not in own and "submitted_by_user_id" not in own,
            "submitter fields present",
        )
        self.sign_in(self.other, self.other_email)
        status, _ = self.job_status(self.other, job_id)
        self.check("another user gets 404 for the job", status == 404, f"HTTP {status}")
        response = self.other.call("GET", "/jobs")
        other_ids = [job.get("id") for job in (response.json() or {}).get("jobs") or []]
        self.check("another user's /jobs omits the job", job_id not in other_ids, "job listed")
        status, record = self.job_status(self.admin, job_id)
        self.check(
            "admin sees the job with the submitter's email",
            status == 200 and record.get("submitted_by_email", "").lower() == self.user_email.lower(),
            f"HTTP {status}",
        )

        if not self.args.simulate_worker:
            self.skip("simulated worker steps", "--no-simulate-worker")
            return
        if not self.claim(job_id):
            return
        response = self.worker.call(
            "PATCH",
            f"/jobs/{job_id}/progress",
            {"current_step": "smoke test: fetching papers", "phase": "fetching"},
        )
        self.expect("worker reports progress", response, 204)
        status, record = self.job_status(self.user, job_id)
        self.check(
            "owner sees the job running with its progress",
            status == 200 and record.get("status") == "running"
            and "smoke test" in (record.get("current_step") or ""),
            f"HTTP {status} status={record.get('status')!r}",
        )
        if self.args.complete_with_fake_result:
            result = {
                "smoke_test": True,
                "annotation": {"annotation_metadata": {"generated_at": datetime.now(UTC).isoformat()}},
            }
            response = self.worker.call(
                "POST", f"/jobs/{job_id}/complete", {"result": result, "worker_id": self.worker.worker_id}
            )
            self.expect("worker completes the job", response, 204)
            expected = "completed"
        else:
            response = self.worker.call(
                "POST",
                f"/jobs/{job_id}/fail",
                {"error": "smoke test: simulated failure", "retryable": False, "worker_id": self.worker.worker_id},
            )
            self.expect("worker fails the job (no fake annotation written)", response, 204)
            expected = "failed"
        status, record = self.job_status(self.user, job_id)
        self.check(
            f"owner sees the job {expected}",
            status == 200 and record.get("status") == expected,
            f"HTTP {status} status={record.get('status')!r}",
        )
        if expected == "completed":
            response = self.user.call("GET", f"/jobs/{job_id}/result")
            self.check(
                "owner reads the result",
                response.status == 200 and (response.json() or {}).get("smoke_test") is True,
                f"HTTP {response.status}",
            )
            if record.get("annotation_error"):
                self.info(f"annotation not stored: {record['annotation_error']}")
            elif record.get("annotation_persisted"):
                self.info("fake result was written to the MongoDB annotation library")
        status, _ = self.job_status(self.other, job_id)
        self.check(f"another user still gets 404 for the {expected} job", status == 404, f"HTTP {status}")
        response = self.other.call("GET", f"/jobs/{job_id}/result")
        self.expect("another user gets 404 for the result", response, 404)

    def cancel_flow(self):
        job_id = self.submit(self.user, "user submits a second job")
        if not job_id:
            return
        claimed = self.args.simulate_worker and self.worker.worker_id and self.claim(job_id)
        response = self.other.call("POST", f"/jobs/{job_id}/cancel")
        self.expect("another user cannot cancel the job", response, 404)
        response = self.user.call("POST", f"/jobs/{job_id}/cancel")
        self.check(
            f"owner cancels the {'running' if claimed else 'queued'} job",
            response.status == 200 and (response.json() or {}).get("status") == "cancelled",
            f"HTTP {response.status} {response.detail()}",
        )
        response = self.user.call("POST", f"/jobs/{job_id}/cancel")
        self.expect("cancelling again answers 409", response, 409)
        if not (self.args.simulate_worker and self.worker.worker_id):
            return
        response = self.worker.call(
            "PATCH", f"/jobs/{job_id}/progress", {"current_step": "smoke test: after cancel"}
        )
        self.check(
            "worker progress on a cancelled job gets 409",
            response.status == 409 and (response.json() or {}).get("cancelled") is True,
            f"HTTP {response.status} {response.detail()}",
        )
        if claimed:
            response = self.worker.call(
                "POST",
                f"/jobs/{job_id}/complete",
                {"result": {"smoke_test": True}, "worker_id": self.worker.worker_id},
            )
            status, record = self.job_status(self.user, job_id)
            self.check(
                "a late complete leaves the job cancelled",
                response.status == 204 and record.get("status") == "cancelled",
                f"HTTP {response.status} status={record.get('status')!r}",
            )
            self.heartbeat()

    def paused_flow(self):
        response = self.user.call("POST", "/jobs", {"profile": self.args.profile, "locus": self.args.locus})
        if response.status == 201:
            self.job_ids.append((response.json() or {}).get("job_id"))
        self.check(
            "SUBMISSIONS_PAUSED: user submit gets 503 paused",
            response.status == 503 and (response.json() or {}).get("code") == "paused",
            f"HTTP {response.status} {response.detail()}",
        )
        data = self.user.call("GET", "/jobs/queue-status").json() or {}
        self.check(
            "SUBMISSIONS_PAUSED: queue-status reports paused",
            data.get("paused") is True and data.get("accepting") is False,
            f"paused={data.get('paused')!r} accepting={data.get('accepting')!r}",
        )

    def quota_flow(self):
        data = self.user.call("GET", "/jobs/queue-status").json() or {}
        today, limit = data.get("your_today", 0), data.get("your_daily_limit")
        if limit is None or today < limit:
            if today < 1:
                self.skip("quota 429", "the user has no jobs today to set a limit at")
                return
            response = self.admin.call(
                "PATCH", f"/admin/users/{self.user.user['id']}", {"quota_max_per_day": today}
            )
            self.expect(f"admin sets the user's daily quota to {today}", response, 200)
        response = self.user.call("POST", "/jobs", {"profile": self.args.profile, "locus": self.args.locus})
        if response.status == 201:
            self.job_ids.append((response.json() or {}).get("job_id"))
        code = (response.json() or {}).get("code")
        self.check(
            "over-quota submit gets 429 with a code",
            response.status == 429 and bool(code),
            f"HTTP {response.status} {response.detail()}",
        )
        if response.status == 429:
            self.info(f"quota code: {code}")

    def audit_checks(self):
        response = self.admin.call("GET", f"/admin/audit?user_id={self.user.user['id']}")
        events = (response.json() or {}).get("events") or []
        actions = {event.get("action") for event in events}
        wanted = {"signup", "login"}
        if self.job_ids:
            wanted |= {"job_submit", "job_cancel"}
        self.check("audit log records the user's actions", wanted <= actions, f"missing {sorted(wanted - actions)}")
        signup = next((event for event in events if event.get("action") == "signup"), None)
        if signup:
            self.info(
                f"client IP recorded for the smoke signup: {signup.get('ip')} "
                "(behind Caddy this should be your public IP, not a private/Docker address)"
            )

    def deletion_checks(self, user_id, email):
        response = self.admin.call("GET", f"/admin/audit?action=user_delete&user_id={user_id}")
        events = (response.json() or {}).get("events") or []
        stored = events[0].get("details", {}).get("email") if events else None
        self.check(
            "user_delete audit event keeps only a masked email",
            bool(stored) and "***" in stored and stored != email,
            "no user_delete event" if not events else "email is not masked",
        )
        if user_id != (self.user.user or {}).get("id"):
            return
        owned = []
        for job_id in filter(None, self.job_ids):
            status, record = self.job_status(self.admin, job_id)
            if status == 200 and (record.get("submitted_by_user_id") or record.get("submitted_by_email")):
                owned.append(job_id[:8])
        self.check("deleted user's jobs have no submitter", not owned, f"still linked: {owned}")

    def cleanup(self):
        print("---- cleanup", flush=True)
        for job_id in self.job_ids:
            if not job_id or not self.admin.cookie:
                continue
            status, record = self.job_status(self.admin, job_id)
            if status == 200 and record.get("status") in ("queued", "running"):
                response = self.admin.call("POST", f"/jobs/{job_id}/cancel")
                self.expect(f"cancel leftover smoke job {job_id[:8]}", response, 200)
        if self.worker.worker_id:
            response = self.worker.call("DELETE", f"/workers/{self.worker.worker_id}")
            self.expect("deregister the simulated worker", response, 204)
        for session, email in ((self.user, self.user_email), (self.other, self.other_email)):
            if not session.user or not self.admin.cookie:
                continue
            response = self.admin.call("DELETE", f"/admin/users/{session.user['id']}")
            self.expect(f"admin deletes {email}", response, 200)
            self.expect(f"deleted account's session no longer works ({session.label})", session.call("GET", "/auth/me"), 401)
            if response.status == 200:
                self.deletion_checks(session.user["id"], email)
        if self.admin.cookie:
            self.admin.call("POST", "/auth/logout")
            self.expect("admin signs out", self.admin.call("GET", "/auth/me"), 401)

    def run(self):
        print(f"Smoke test against {self.base} (worker routes: {self.worker_url})", flush=True)
        try:
            self.public_pages()
            self.worker_routes()
            self.admin_checks()
            self.user_checks()
            if self.args.expect_paused:
                self.paused_flow()
            else:
                self.job_flow()
                self.cancel_flow()
                self.quota_flow()
            self.audit_checks()
        except SmokeAbort as exc:
            self.report("FAIL", "aborted", str(exc))
        except (OSError, urllib.error.URLError) as exc:
            self.report("FAIL", "aborted: connection error", str(exc))
        finally:
            try:
                self.cleanup()
            except (OSError, urllib.error.URLError, SmokeAbort) as exc:
                self.report("FAIL", "cleanup", str(exc))
        print(
            f"==== {self.results['PASS']} passed, {self.results['FAIL']} failed, "
            f"{self.results['SKIP']} skipped",
            flush=True,
        )
        return 1 if self.results["FAIL"] else 0


def build_parser():
    parser = argparse.ArgumentParser(
        description="End-to-end smoke test for a Gene Autoannotator deployment.",
        epilog="See the module docstring (or deploy/docs/launch-runbook.md) for examples.",
    )
    parser.add_argument("base_url", help="Site URL the browser uses, e.g. https://example.org")
    parser.add_argument(
        "--worker-url",
        help="Where workers reach the worker routes (default: base_url, i.e. through Caddy)",
    )
    parser.add_argument(
        "--i-understand-this-creates-accounts",
        dest="confirmed",
        action="store_true",
        help="Required: signs in the admin and creates (then deletes) two +smoke accounts",
    )
    parser.add_argument("--admin-email", default=BOOTSTRAP_ADMIN_EMAIL)
    parser.add_argument(
        "--admin-login",
        action="store_true",
        help="Sign the admin in with /auth/login instead of /auth/signup (saves a per-IP sign-up)",
    )
    otp = parser.add_mutually_exclusive_group(required=True)
    otp.add_argument("--otp-log-file", help="File containing the backend's console-email output")
    otp.add_argument("--otp-command", help="Shell command that prints the backend's console-email output")
    otp.add_argument("--otp-prompt", action="store_true", help="Ask for each code (real email delivery)")
    parser.add_argument("--otp-timeout", type=int, default=30, help="Seconds to wait for a code (default 30)")
    parser.add_argument(
        "--worker-token-file",
        help="File holding WORKER_API_TOKEN (default: the WORKER_API_TOKEN environment variable)",
    )
    parser.add_argument(
        "--no-simulate-worker",
        dest="simulate_worker",
        action="store_false",
        help="Skip the worker steps (no token needed)",
    )
    parser.add_argument(
        "--complete-with-fake-result",
        action="store_true",
        help="Complete the smoke job instead of failing it; writes to the annotation library if MongoDB is set",
    )
    parser.add_argument(
        "--no-mongo",
        action="store_true",
        help="The deployment runs without MongoDB: skip the annotation-library query instead of failing",
    )
    parser.add_argument(
        "--expect-paused",
        action="store_true",
        help="The backend runs with SUBMISSIONS_PAUSED=1: check the 503 instead of the job steps",
    )
    parser.add_argument("--profile", default="mtb-h37rv", help="Profile of the smoke job (default mtb-h37rv)")
    parser.add_argument("--locus", default="Rv0001", help="Locus of the smoke job (default Rv0001)")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.confirmed:
        parser.error("refusing to run without --i-understand-this-creates-accounts")
    args.worker_token = None
    if args.simulate_worker:
        if args.worker_token_file:
            args.worker_token = Path(args.worker_token_file).read_text(encoding="utf-8").strip()
        else:
            args.worker_token = (os.environ.get("WORKER_API_TOKEN") or "").strip()
        if not args.worker_token:
            parser.error("set WORKER_API_TOKEN (or --worker-token-file), or pass --no-simulate-worker")
    return Smoke(args).run()


if __name__ == "__main__":
    sys.exit(main())
