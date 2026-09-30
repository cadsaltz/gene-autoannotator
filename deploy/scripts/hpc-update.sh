#!/usr/bin/env bash
# Update the HPC checkout (dispatcher code + dispatcher venv) and the worker SIF
# together. Meant for scrontab, e.g. daily:
#   17 4 * * * /shared/gene-autoannotator/deploy/scripts/hpc-update.sh
#
# Each run: git fetch; compute the worker image key of the upstream tip
# (deploy/scripts/worker-image-key.sh as of that commit) and pull
# ghcr.io/cadsaltz/gene-autoannotator-worker:src-<key> into
# $SIF_DIR/worker-src-<key>.sif (skipped if present); only then fast-forward the
# checkout, so code and worker image always move together. Until CI has
# published that image the run logs "waiting" and changes nothing. Then it
# points worker-current.sif at the SIF (set
# WORKER_IMAGE=<SIF_DIR>/worker-current.sif in dispatcher.env), reinstalls the
# venv when the requirements files changed, and deletes old SIFs and old
# Apptainer cache entries. A run with nothing new logs one line. Overlapping
# runs exit at once.
#
# Private GHCR images need a one-time login with a read:packages token:
#   apptainer registry login --username <github-user> docker://ghcr.io
#
# Environment (all optional):
#   GAA_REPO             checkout to update (default: this script's repo)
#   GAA_VENV             dispatcher venv (default: <repo>/.venv; skipped if missing)
#   GAA_REQUIREMENTS     space-separated requirements files installed into the venv
#                        (default: "requirements.txt requirements-web.txt")
#   GAA_PULL_SIF         0 = only update code and venv; WORKER_IMAGE is managed by hand
#   GAA_SIF_DIR          SIF directory (default: <repo>/sif)
#   GAA_WORKER_IMAGE     image repo (default: ghcr.io/cadsaltz/gene-autoannotator-worker)
#   GAA_SIF_KEEP         newest SIFs always kept (default: 2)
#   GAA_SIF_GRACE_HOURS  an older SIF is deleted only once the SIF that replaced it
#                        has been current this long, so allocations started on it
#                        have ended (default: 48, the #SBATCH --time of worker-run.sbatch)
#   GAA_CACHE_DAYS       Apptainer cache entries older than this are removed (default: 14)
#   GAA_HPC_UPDATE_LOG   log file (default: <repo>/hpc-update.log)
#   GAA_HPC_UPDATE_LOCK  lock file (default: <repo>/.hpc-update.lock)
#   APPTAINER            apptainer binary (default: apptainer; singularity also works)
#   APPTAINER_CACHEDIR   layer cache (default: <SIF_DIR>/.cache)
#   APPTAINER_TMPDIR     scratch for the image conversion (default: <SIF_DIR>/.tmp)
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${GAA_REPO:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
VENV="${GAA_VENV:-$REPO/.venv}"
read -r -a REQUIREMENTS <<<"${GAA_REQUIREMENTS:-requirements.txt requirements-web.txt}"
PULL_SIF="${GAA_PULL_SIF:-1}"
SIF_DIR="${GAA_SIF_DIR:-$REPO/sif}"
WORKER_IMAGE_REPO="${GAA_WORKER_IMAGE:-ghcr.io/cadsaltz/gene-autoannotator-worker}"
SIF_KEEP="${GAA_SIF_KEEP:-2}"
((SIF_KEEP >= 1)) || SIF_KEEP=1
SIF_GRACE_HOURS="${GAA_SIF_GRACE_HOURS:-48}"
CACHE_DAYS="${GAA_CACHE_DAYS:-14}"
LOG_FILE="${GAA_HPC_UPDATE_LOG:-$REPO/hpc-update.log}"
LOCK_FILE="${GAA_HPC_UPDATE_LOCK:-$REPO/.hpc-update.lock}"
APPTAINER="${APPTAINER:-apptainer}"
export APPTAINER_CACHEDIR="${APPTAINER_CACHEDIR:-$SIF_DIR/.cache}"
export APPTAINER_TMPDIR="${APPTAINER_TMPDIR:-$SIF_DIR/.tmp}"
CURRENT_LINK="$SIF_DIR/worker-current.sif"

exec >>"$LOG_FILE" 2>&1

log() {
  printf '%s [hpc-update] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  log "another update is running; skipping"
  exit 0
fi

trap 'log "update FAILED (exit $?)"' ERR

git_() {
  git -C "$REPO" "$@"
}

# Runs the key script from the target commit, so its path list matches the
# Dockerfile being deployed.
image_key() {
  (cd "$REPO" && git show "$1:deploy/scripts/worker-image-key.sh" | bash -s -- "$1")
}

requirements_hash() {
  (cd "$REPO" && cat -- "${REQUIREMENTS[@]}") | sha256sum | cut -d' ' -f1
}

# Called in a condition, where set -e is off, hence the explicit returns. Pulls
# to a hidden temp name first: worker-current.sif must never point at a partly
# written file.
ensure_sif() {
  local tag="$1" sif="$SIF_DIR/worker-$1.sif" tmp="$SIF_DIR/.worker-$1.sif.partial"
  [[ -f "$sif" ]] && return 0
  mkdir -p "$SIF_DIR" "$APPTAINER_CACHEDIR" "$APPTAINER_TMPDIR" || return 1
  rm -f "$tmp" || return 1
  log "pulling $WORKER_IMAGE_REPO:$tag"
  if ! "$APPTAINER" pull "$tmp" "docker://$WORKER_IMAGE_REPO:$tag"; then
    rm -f "$tmp"
    return 1
  fi
  mv -f "$tmp" "$sif" || return 1
  log "pulled $sif"
}

# The target's mtime is set to when it became current; prune_sifs relies on it.
link_current() {
  local target="worker-$1.sif"
  if [[ "$(readlink "$CURRENT_LINK" 2>/dev/null || true)" == "$target" ]]; then
    return 0
  fi
  touch "$SIF_DIR/$target"
  ln -sfn "$target" "$CURRENT_LINK.new"
  mv -Tf "$CURRENT_LINK.new" "$CURRENT_LINK"
  log "worker-current.sif -> $target"
}

prune_sifs() {
  local now grace_s successor_mtime current i
  local -a sifs
  now="$(date +%s)"
  grace_s=$((SIF_GRACE_HOURS * 3600))
  current="$SIF_DIR/$(readlink "$CURRENT_LINK" 2>/dev/null || true)"
  mapfile -t sifs < <(find "$SIF_DIR" -maxdepth 1 -type f -name 'worker-src-*.sif' -printf '%T@ %p\n' \
    | sort -rn | cut -d' ' -f2-)
  for ((i = SIF_KEEP; i < ${#sifs[@]}; i++)); do
    [[ "${sifs[i]}" == "$current" ]] && continue
    successor_mtime="$(stat -c %Y "${sifs[i - 1]}")"
    if ((now - successor_mtime >= grace_s)); then
      rm -f "${sifs[i]}"
      log "removed ${sifs[i]}"
    fi
  done
  if ! "$APPTAINER" cache clean -f --days "$CACHE_DAYS" >/dev/null; then
    log "WARNING: apptainer cache clean failed"
  fi
}

old="$(git_ rev-parse HEAD)"
if ! upstream="$(git_ rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null)"; then
  log "ERROR: $REPO has no upstream branch (detached HEAD?); nothing done"
  exit 1
fi
git_ fetch --quiet
new="$(git_ rev-parse '@{u}')"

if ! git_ merge-base --is-ancestor "$old" "$new"; then
  if git_ merge-base --is-ancestor "$new" "$old"; then
    new="$old"
  else
    log "ERROR: $upstream has diverged from HEAD ${old:0:7}; fix the checkout by hand"
    exit 1
  fi
fi

if [[ "$PULL_SIF" == 1 ]]; then
  if ! key="$(image_key "$new")" || [[ -z "$key" ]]; then
    log "ERROR: cannot compute the worker image key of ${new:0:7}; nothing done"
    exit 1
  fi
  tag="src-$key"
  if ! ensure_sif "$tag"; then
    log "waiting: $WORKER_IMAGE_REPO:$tag (for ${new:0:7}) is not pullable yet (images still building, CI failed, or no registry login); staying at ${old:0:7}"
    exit 0
  fi
fi

if [[ "$new" != "$old" ]]; then
  git_ merge --ff-only --quiet "$new"
  log "code ${old:0:7} -> ${new:0:7}"
fi

if [[ "$PULL_SIF" == 1 ]]; then
  link_current "$tag"
fi

if [[ -x "$VENV/bin/python" ]]; then
  stamp="$VENV/.gaa-requirements.sha256"
  want="$(requirements_hash)"
  if [[ "$(cat "$stamp" 2>/dev/null || true)" != "$want" ]]; then
    log "requirements changed; reinstalling into $VENV"
    (cd "$REPO" && "$VENV/bin/python" -m pip install --quiet "${REQUIREMENTS[@]/#/--requirement=}")
    printf '%s\n' "$want" >"$stamp"
    log "venv up to date"
  fi
else
  log "no venv at $VENV; skipping dependency install"
fi

if [[ "$PULL_SIF" == 1 ]]; then
  prune_sifs
fi

if [[ "$new" == "$old" ]]; then
  log "up to date at ${old:0:7}"
else
  log "update done"
fi
