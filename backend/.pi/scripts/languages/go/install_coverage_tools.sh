#!/usr/bin/env bash
# ============================================================================
# install_coverage_tools.sh — Go: no extra install required
#
# `go test -coverprofile` is built into the Go toolchain. This script exists
# so the language dispatcher is uniform; it only verifies the toolchain is
# present.
# ============================================================================
set -euo pipefail

if command -v go >/dev/null 2>&1; then
    echo "Go coverage tooling is built-in (go version $(go version | awk '{print $3}'))."
    exit 0
fi

echo "✗ go toolchain not found — install Go (https://go.dev/dl/) to use the coverage gate." >&2
exit 1
