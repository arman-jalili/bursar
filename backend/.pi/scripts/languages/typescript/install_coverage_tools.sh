#!/usr/bin/env bash
# ============================================================================
# install_coverage_tools.sh — TypeScript/JavaScript: install a real coverage
# tool
#
# The coverage gate (languages/typescript/coverage.sh) prefers the runner
# your project already uses (vitest → jest → bun → c8). This script installs
# whatever is missing for that chain:
#   - vitest coverage needs the matching provider package
#   - jest coverage is built-in (text reporter via config)
#   - bun test --coverage is built into the Bun runtime (no install)
#   - c8 is a universal fallback that wraps `npm test`
#
# Run this inside the project root (where package.json lives).
# ============================================================================
set -euo pipefail

if [ ! -f "package.json" ]; then
    echo "✗ No package.json found in the current directory" >&2
    exit 1
fi

if grep -q '"vitest"' package.json; then
    if grep -q 'coverage-v8\|coverage-istanbul' package.json; then
        echo "vitest + coverage provider present."
    else
        echo "vitest detected — installing @vitest/coverage-v8 (required for vitest --coverage)..."
        npm install --save-dev @vitest/coverage-v8 \
            || { echo "✗ install failed — run: npm install --save-dev @vitest/coverage-v8" >&2; exit 1; }
    fi
elif grep -q '"jest"' package.json; then
    echo "jest detected — enable 'coverageReporters': ['text', 'lcov'] in jest config for the coverage gate."
elif command -v bun >/dev/null 2>&1; then
    echo "bun detected — 'bun test --coverage' is built in; no install needed."
else
    echo "No vitest/jest/bun detected — installing c8 as a universal coverage runner..."
    npm install --save-dev c8 \
        || { echo "✗ install failed — run: npm install --save-dev c8" >&2; exit 1; }
fi

echo "TypeScript coverage tooling ready."
