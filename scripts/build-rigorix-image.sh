#!/usr/bin/env bash
# Build the governed-execution host image (rigorix-server + the Bursar broadcaster).
#
# Why this script exists: backend/Dockerfile.rigorix expects a build context with both
# `rigorix-oss/` and `proximata/bursar/backend/` at its root. In a development checkout the
# parent directory also holds rigorix-oss/target (tens of GB), so `docker build ../..` sends an
# enormous context. This assembles a clean context first.
#
#   ./scripts/build-rigorix-image.sh                 # native arch (build on the VPS for amd64)
#   TAG=registry.example.com/bursar-rigorix:1 ./scripts/build-rigorix-image.sh
#   PLATFORM=linux/amd64 TAG=... ./scripts/build-rigorix-image.sh   # cross-build (buildx)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RIGORIX_DIR="${RIGORIX_OSS:-$ROOT/../../rigorix-oss}"
TAG="${TAG:-bursar-rigorix:dev}"
PLATFORM="${PLATFORM:-}"
CONTEXT="$(mktemp -d -t bursar-rigorix-build.XXXXXX)"
trap 'rm -rf "$CONTEXT"' EXIT

if [[ ! -d "$RIGORIX_DIR" ]]; then
  echo "rigorix-oss not found at $RIGORIX_DIR (set RIGORIX_OSS=/path/to/rigorix-oss)" >&2
  exit 1
fi

echo "assembling clean build context in $CONTEXT"
mkdir -p "$CONTEXT/rigorix-oss" "$CONTEXT/proximata/bursar"
rsync -a \
  --exclude 'target/' \
  --exclude '.git/' \
  --exclude '.gitnexus/' \
  --exclude 'node_modules/' \
  --exclude 'benchmarks/' \
  "$RIGORIX_DIR/" "$CONTEXT/rigorix-oss/"
rsync -a \
  --exclude '.venv/' \
  --exclude 'data/' \
  --exclude '**/__pycache__/' \
  --exclude '.pytest_cache/' \
  "$ROOT/backend/" "$CONTEXT/proximata/bursar/backend/"

echo "building $TAG (platform: ${PLATFORM:-native})"
if [[ -n "$PLATFORM" ]]; then
  docker buildx build --platform "$PLATFORM" --load \
    -f "$CONTEXT/proximata/bursar/backend/Dockerfile.rigorix" \
    -t "$TAG" "$CONTEXT"
else
  docker build \
    -f "$CONTEXT/proximata/bursar/backend/Dockerfile.rigorix" \
    -t "$TAG" "$CONTEXT"
fi

echo "image ready: $TAG"
echo "run it with: BURSAR_RIGORIX_BASE_URL=http://rigorix:3001 docker compose --profile container-rigorix up -d"
