#!/usr/bin/env bash
# Print the content key of the worker image for a commit: a hash of the git
# object ids of everything deploy/docker/Dockerfile.worker is built from. The
# image is published as ghcr.io/cadsaltz/gene-autoannotator-worker:src-<key>
# (.github/workflows/images.yml) and pulled by that tag (hpc-update.sh), so
# commits that don't touch these paths reuse the same image.
#
# Usage: worker-image-key.sh [COMMIT]   (default HEAD; run inside the checkout)
#        worker-image-key.sh --paths    (list the paths)
set -euo pipefail

# Every COPY source in Dockerfile.worker, plus the Dockerfile and .dockerignore.
# tests/test_worker_image_key.py fails if this drifts from the Dockerfile.
WORKER_IMAGE_PATHS=(
  deploy/docker/Dockerfile.worker
  .dockerignore
  requirements.txt
  requirements-web.txt
  autoannotation
  worker
  shared
  goresolve
  data/profiles
  deploy/docker/worker-bench-entrypoint.sh
  deploy/docker/worker-run-entrypoint.sh
)

if [[ "${1:-}" == --paths ]]; then
  printf '%s\n' "${WORKER_IMAGE_PATHS[@]}"
  exit 0
fi

commit="$(git rev-parse --verify --quiet "${1:-HEAD}^{commit}")" || {
  echo "worker-image-key.sh: not a commit: ${1:-HEAD}" >&2
  exit 1
}

ids=""
for path in "${WORKER_IMAGE_PATHS[@]}"; do
  id="$(git rev-parse --verify --quiet "$commit:$path")" || {
    echo "worker-image-key.sh: $path missing in $commit" >&2
    exit 1
  }
  ids+="$id $path"$'\n'
done
printf '%s' "$ids" | sha256sum | cut -c1-16
