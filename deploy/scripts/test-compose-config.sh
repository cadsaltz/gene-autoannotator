#!/usr/bin/env bash
# Render docker-compose.prod.yml (prod, prod + worker-port override, staging)
# with the example env files, and validate the Caddyfile when caddy is on PATH.
# Exits 0 with a SKIP line for each tool that is not installed.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_DIR="$REPO_ROOT/deploy/compose"

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  COMPOSE=()
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

cp "$COMPOSE_DIR/docker-compose.prod.yml" "$COMPOSE_DIR/docker-compose.worker-port.yml" \
  "$COMPOSE_DIR/Caddyfile" "$tmp/"
for name in backend frontend; do
  cp "$COMPOSE_DIR/$name.prod.env.example" "$tmp/$name.env"
  cp "$COMPOSE_DIR/$name.prod.env.example" "$tmp/$name.staging.env"
done
cp "$COMPOSE_DIR/compose.env.example" "$tmp/compose.env"
cp "$COMPOSE_DIR/compose.staging.env.example" "$tmp/compose.staging.env"

if [[ ${#COMPOSE[@]} -gt 0 ]]; then
  render() {
    local label="$1"
    shift
    "${COMPOSE[@]}" "$@" config -q
    echo "OK compose config: $label"
  }
  render prod -p gaa -f "$tmp/docker-compose.prod.yml" --env-file "$tmp/compose.env"
  render "prod + worker-port" -p gaa -f "$tmp/docker-compose.prod.yml" \
    -f "$tmp/docker-compose.worker-port.yml" --env-file "$tmp/compose.env"
  render staging -p gaa-staging -f "$tmp/docker-compose.prod.yml" --env-file "$tmp/compose.staging.env"
else
  echo "SKIP compose config: neither 'docker compose' nor 'docker-compose' is installed"
fi

if command -v caddy >/dev/null 2>&1; then
  for site in ":80" "annotator.example.org"; do
    SITE_ADDRESS="$site" caddy validate --config "$tmp/Caddyfile" --adapter caddyfile >/dev/null 2>&1 \
      || { SITE_ADDRESS="$site" caddy validate --config "$tmp/Caddyfile" --adapter caddyfile; exit 1; }
    echo "OK caddy validate: SITE_ADDRESS=$site"
  done
elif docker info >/dev/null 2>&1; then
  for site in ":80" "annotator.example.org"; do
    docker run --rm -e SITE_ADDRESS="$site" -v "$tmp/Caddyfile:/etc/caddy/Caddyfile:ro" caddy:2.10 \
      caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null
    echo "OK caddy validate (docker): SITE_ADDRESS=$site"
  done
else
  echo "SKIP caddy validate: neither caddy nor a running docker daemon is available"
fi
