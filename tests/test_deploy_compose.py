import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_DIR = REPO_ROOT / "deploy" / "compose"
PROD = COMPOSE_DIR / "docker-compose.prod.yml"
WORKER_PORT = COMPOSE_DIR / "docker-compose.worker-port.yml"
CADDYFILE = COMPOSE_DIR / "Caddyfile"
BACKEND_ENV = COMPOSE_DIR / "backend.prod.env.example"
FRONTEND_ENV = COMPOSE_DIR / "frontend.prod.env.example"

SAMPLE_ID = "0f3c9a2e-job"


def _load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def prod():
    return _load(PROD)


# --- compose -----------------------------------------------------------------


def test_services_are_exactly_backend_frontend_caddy(prod):
    assert set(prod["services"]) == {"backend", "frontend", "caddy"}


def test_project_name_differs_from_the_old_stack(prod):
    # docker-compose.backend.yml runs as project "compose" (its directory name).
    assert prod["name"] == "gaa"


def test_no_service_builds_images(prod):
    for name, service in prod["services"].items():
        assert "build" not in service, name


def test_all_services_restart_unless_stopped(prod):
    for name, service in prod["services"].items():
        assert service.get("restart") == "unless-stopped", name


def test_app_images_come_from_ghcr_with_image_tag(prod):
    services = prod["services"]
    assert services["backend"]["image"] == "ghcr.io/cadsaltz/gene-autoannotator-backend:${IMAGE_TAG:-prod}"
    assert services["frontend"]["image"] == "ghcr.io/cadsaltz/gene-autoannotator-frontend:${IMAGE_TAG:-prod}"
    assert services["caddy"]["image"].startswith("caddy:2")


def test_only_caddy_publishes_ports(prod):
    for name, service in prod["services"].items():
        if name == "caddy":
            continue
        assert "ports" not in service, name
        assert "network_mode" not in service, name
    ports = prod["services"]["caddy"]["ports"]
    assert "${CADDY_HTTP_PORT:-80}:80" in ports
    assert "${CADDY_HTTPS_PORT:-443}:443" in ports


def test_worker_port_override_only_adds_a_caddy_port():
    override = _load(WORKER_PORT)
    assert set(override["services"]) == {"caddy"}
    assert override["services"]["caddy"] == {"ports": ["${CADDY_WORKER_PORT:-8000}:8000"]}


def test_env_files_are_split_per_service(prod):
    services = prod["services"]
    assert services["backend"]["env_file"] == ["${BACKEND_ENV_FILE:-backend.env}"]
    assert services["frontend"]["env_file"] == ["${FRONTEND_ENV_FILE:-frontend.env}"]
    assert "env_file" not in services["caddy"]


def test_caddy_requires_site_address(prod):
    site = prod["services"]["caddy"]["environment"]["SITE_ADDRESS"]
    assert site.startswith("${SITE_ADDRESS:?")


def test_named_volumes_are_declared_and_mounted(prod):
    assert set(prod["volumes"]) == {"backend-data", "profiles-data", "caddy-data", "caddy-config"}
    services = prod["services"]
    assert services["backend"]["volumes"] == [
        "backend-data:/state/backend",
        "profiles-data:/app/data/profiles",
    ]
    assert services["backend"]["environment"]["PROFILES_DIR"] == "/app/data/profiles"
    assert "caddy-data:/data" in services["caddy"]["volumes"]
    assert "caddy-config:/config" in services["caddy"]["volumes"]
    assert "./Caddyfile:/etc/caddy/Caddyfile:ro" in services["caddy"]["volumes"]
    assert "volumes" not in services["frontend"]


# --- Caddyfile routing -------------------------------------------------------


def _caddy_matcher_paths():
    text = CADDYFILE.read_text(encoding="utf-8")
    match = re.search(r"^\s*@backend path (.+)$", text, re.MULTILINE)
    assert match, "Caddyfile must define the @backend path matcher"
    return match.group(1).split()


def _caddy_path_matches(pattern, path):
    """Caddy's path matcher: case-insensitive; `*` at the end is a prefix match,
    in the middle a glob where `*` does not cross `/`."""
    pattern, path = pattern.lower(), path.lower()
    if "*" not in pattern:
        return path == pattern
    if pattern.endswith("*") and "*" not in pattern[:-1]:
        return path.startswith(pattern[:-1])
    regex = "^" + "[^/]*".join(re.escape(part) for part in pattern.split("*")) + "$"
    return re.match(regex, path) is not None


def _routes_to_backend(path):
    return any(_caddy_path_matches(pattern, path) for pattern in _caddy_matcher_paths())


def _fill(path):
    return re.sub(r"\{[^}]+\}|\$\{[^}]+\}", SAMPLE_ID, path)


def _worker_client_paths():
    text = (REPO_ROOT / "worker" / "client.py").read_text(encoding="utf-8")
    return sorted({_fill(p) for p in re.findall(r'f?"(/(?:workers|jobs)[^"]*)"', text)})


def _dispatcher_paths():
    text = (REPO_ROOT / "dispatcher" / "loop.py").read_text(encoding="utf-8")
    return sorted({_fill(p) for p in re.findall(r'f"\{backend_url\}(/[^"]*)"', text)})


def _script_paths():
    scripts = REPO_ROOT / "deploy" / "scripts"
    update = (scripts / "update-worker.sh").read_text(encoding="utf-8")
    drain = re.findall(r'"\$\{BASE\}(/workers/\$\{worker_id\}/[a-z]+)"', update)
    reach = (scripts / "test-backend-reachability.sh").read_text(encoding="utf-8")
    health = re.findall(r'"\$URL(/[a-z]+)"', reach)
    return sorted({_fill(p) for p in drain + health})


def test_path_extraction_finds_every_worker_call():
    assert _worker_client_paths() == sorted(
        {
            "/workers/register",
            f"/workers/{SAMPLE_ID}",
            f"/workers/{SAMPLE_ID}/heartbeat",
            f"/workers/{SAMPLE_ID}/claim",
            f"/jobs/{SAMPLE_ID}/progress",
            f"/jobs/{SAMPLE_ID}/complete",
            f"/jobs/{SAMPLE_ID}/fail",
        }
    )
    assert _dispatcher_paths() == ["/jobs/queue-summary"]
    assert _script_paths() == ["/healthz", f"/workers/{SAMPLE_ID}/drain"]


def test_every_worker_and_dispatcher_path_routes_to_backend():
    paths = _worker_client_paths() + _dispatcher_paths() + _script_paths()
    unrouted = [path for path in paths if not _routes_to_backend(path)]
    assert unrouted == []


def _frontend_page_paths():
    app = REPO_ROOT / "frontend" / "app"
    pages = []
    for page in app.rglob("page.js"):
        route = "/" + "/".join(page.relative_to(app).parent.parts)
        pages.append(route if route != "/." else "/")
    return pages


def test_frontend_pages_and_browser_api_stay_on_the_frontend():
    pages = _frontend_page_paths()
    assert "/jobs" in pages and "/admin/users" in pages
    browser_paths = pages + [
        "/",
        "/jobs/",
        f"/jobs/{SAMPLE_ID}",
        f"/jobs/{SAMPLE_ID}/result",
        f"/jobs/{SAMPLE_ID}/cancel",
        "/jobs/queue-status",
        "/jobs/history",
        "/workers",
        "/health",
        "/backend-info",
        "/auth/login",
        "/auth/me",
        "/admin/users",
        "/admin/overview",
        "/profiles",
        "/api/backend/auth/login",
        "/api/backend/workers/register",
        "/api/annotations/search",
        f"/jobs/a/{SAMPLE_ID}/progress",
        "/_next/static/chunks/main.js",
        "/robots.txt",
    ]
    leaked = [path for path in browser_paths if _routes_to_backend(path)]
    assert leaked == []


def _backend_routes():
    text = (REPO_ROOT / "backend" / "api.py").read_text(encoding="utf-8")
    decorator = re.compile(r'@app\.(get|post|put|patch|delete)\(\s*"([^"]+)"', re.MULTILINE)
    matches = list(decorator.finditer(text))
    routes = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        routes.append((match.group(1).upper(), match.group(2), text[match.end() : end]))
    return routes


def test_backend_routes_exposed_by_caddy_require_the_worker_token():
    routes = _backend_routes()
    assert len(routes) > 30
    exposed = [(method, path, body) for method, path, body in routes if _routes_to_backend(_fill(path))]
    assert {path for _method, path, _body in exposed} >= {
        "/healthz",
        "/jobs/queue-summary",
        "/workers/register",
        "/jobs/{job_id}/complete",
    }
    unprotected = [
        f"{method} {path}"
        for method, path, body in exposed
        if path != "/healthz" and "_require_worker_token(authorization)" not in body
    ]
    assert unprotected == []


def test_hsts_is_sent_only_over_https():
    text = CADDYFILE.read_text(encoding="utf-8")
    assert re.search(r"^\s*@https protocol https$", text, re.MULTILINE)
    hsts_lines = [line.strip() for line in text.splitlines() if "Strict-Transport-Security" in line]
    assert hsts_lines == ['header @https Strict-Transport-Security "max-age=31536000"']


def test_site_block_uses_site_address_and_proxies_to_compose_services():
    text = CADDYFILE.read_text(encoding="utf-8")
    assert re.search(r"^\{\$SITE_ADDRESS\} \{$", text, re.MULTILINE)
    assert "import proxy backend:8000" in text
    assert "import proxy frontend:3000" in text
    assert "trusted_proxies" not in re.sub(r"#.*", "", text)


def test_every_upstream_gets_x_forwarded_for_from_client_ip():
    text = re.sub(r"#.*", "", CADDYFILE.read_text(encoding="utf-8"))
    assert re.findall(r"reverse_proxy .*", text) == ["reverse_proxy {args[0]} {"]
    assert re.search(r"\(proxy\) \{\s*reverse_proxy \{args\[0\]\} \{\s*header_up X-Forwarded-For \{client_ip\}\s*\}", text)


def _size_bytes(value):
    number, unit = re.fullmatch(r"(\d+)(KB|MB|GB)", value).groups()
    return int(number) * {"KB": 1000, "MB": 1000**2, "GB": 1000**3}[unit]


def test_worker_body_limit_leaves_room_for_large_results():
    text = CADDYFILE.read_text(encoding="utf-8")
    sizes = [_size_bytes(value) for value in re.findall(r"max_size (\S+)", text)]
    assert sizes, "expected request_body limits"
    # Worker handles are the ones proxying to backend:8000.
    worker_blocks = re.findall(r"handle @backend \{(.*?)\n\t\}", text, re.DOTALL)
    assert len(worker_blocks) == 2
    for block in worker_blocks:
        (limit,) = re.findall(r"max_size (\S+)", block)
        assert _size_bytes(limit) >= 32 * 1000**2


# --- env examples ------------------------------------------------------------


def _env_names(path):
    names = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\s*(#\s*)?([A-Z][A-Z0-9_]+)=(.*)$", line)
        if match:
            names.setdefault(match.group(2), (match.group(1) is None, match.group(3)))
    return names


def _backend_env_names_read_by_code():
    pattern = re.compile(
        r'(?:getenv|environ\.get|_env_flag|env_int|env_number|_env_number)\(\s*"([A-Z][A-Z0-9_]+)"'
    )
    names = set()
    for source in (REPO_ROOT / "backend").glob("*.py"):
        names.update(pattern.findall(source.read_text(encoding="utf-8")))
    from backend.rate_limits import RATE_LIMIT_DEFAULTS

    names.update(RATE_LIMIT_DEFAULTS)
    return names


def test_backend_example_lists_every_env_name_the_backend_reads(prod):
    names = _backend_env_names_read_by_code()
    assert {"TRUST_FORWARDED_FOR", "MAX_QUEUED_JOBS", "IP_LOGINS_PER_HOUR", "BACKUP_KEEP"} <= names
    pinned_by_compose = set(prod["services"]["backend"]["environment"])
    assert pinned_by_compose == {"PROFILES_DIR"}
    names -= pinned_by_compose
    documented = set(_env_names(BACKEND_ENV))
    aliases = {"MONGODB_URI": "MONGO_URI"}
    missing = sorted(name for name in names if aliases.get(name, name) not in documented)
    assert missing == []


def test_backend_example_sets_production_values():
    env = _env_names(BACKEND_ENV)
    expected = {
        "REQUIRE_WORKER_API_TOKEN": "1",
        "SESSION_COOKIE_SECURE": "1",
        "TRUST_FORWARDED_FOR": "1",
        "WORKER_CAPACITY_REQUIRED": "0",
        "EMAIL_BACKEND": "resend",
    }
    for name, value in expected.items():
        assert env[name] == (True, value), name
    for name in ("TERMS_VERSION", "SUBMISSIONS_PAUSED"):
        assert env[name][0] is False, f"{name} should be commented out"


def test_frontend_example_lists_every_env_name_the_frontend_reads():
    names = set()
    for source in (REPO_ROOT / "frontend").rglob("*.js"):
        if "node_modules" in source.parts or ".next" in source.parts or source.name.endswith(".test.js"):
            continue
        names.update(re.findall(r"process\.env\.([A-Z][A-Z0-9_]+)", source.read_text(encoding="utf-8")))
    names -= {"NODE_ENV"}
    assert {"MONGO_URI", "BACKEND_API_BASE_URL"} <= names
    env = _env_names(FRONTEND_ENV)
    aliases = {"MONGODB_URI": "MONGO_URI"}
    assert sorted(name for name in names if aliases.get(name, name) not in env) == []
    assert env["BACKEND_API_BASE_URL"] == (True, "http://backend:8000")


def test_secrets_in_examples_are_placeholders():
    for path in (BACKEND_ENV, FRONTEND_ENV):
        env = _env_names(path)
        for name in ("WORKER_API_TOKEN", "RESEND_API_KEY", "MONGO_URI"):
            if name in env:
                assert "CHANGE_ME" in env[name][1], name
