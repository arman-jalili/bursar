#!/usr/bin/env bash
# Build the governed-execution host image (rigorix-server + the Bursar broadcaster).
#
# rigorix-server is installed from crates.io inside the Dockerfile, so there is no sibling
# checkout and no giant build context. Build it on the VPS itself for a native amd64 image.
#
#   ./scripts/build-rigorix-image.sh
#   TAG=registry.example.com/bursar-rigorix:1 ./scripts/build-rigorix-image.sh
#   RIGORIX_VERSION=1.14.3 ./scripts/build-rigorix-image.sh           # override the pinned version
#   PLATFORM=linux/amd64 TAG=... ./scripts/build-rigorix-image.sh     # cross-build (buildx)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TAG="${TAG:-bursar-rigorix:dev}"
PLATFORM="${PLATFORM:-}"
VERSION_ARGS=()
if [[ -n "${RIGORIX_VERSION:-}" ]]; then
  VERSION_ARGS=(--build-arg "RIGORIX_VERSION=$RIGORIX_VERSION")
fi

echo "building $TAG from $ROOT/backend/Dockerfile.rigorix (platform: ${PLATFORM:-native})"
if [[ -n "$PLATFORM" ]]; then
  docker buildx build --platform "$PLATFORM" --load \
    ${VERSION_ARGS[@]+"${VERSION_ARGS[@]}"} \
    -f "$ROOT/backend/Dockerfile.rigorix" -t "$TAG" "$ROOT"
else
  docker build ${VERSION_ARGS[@]+"${VERSION_ARGS[@]}"} \
    -f "$ROOT/backend/Dockerfile.rigorix" -t "$TAG" "$ROOT"
fi

echo "image ready: $TAG"
echo "compose: BURSAR_RIGORIX_BASE_URL=http://rigorix:3001 docker compose --profile container-rigorix up -d"
