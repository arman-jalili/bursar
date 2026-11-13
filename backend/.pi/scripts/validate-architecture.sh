#!/usr/bin/env bash
# validate-architecture.sh — Dispatcher
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

detect_language() {
    if [ -f "poetry.lock" ] || [ -f "pyproject.toml" ]; then echo "python"
    elif [ -f "Cargo.lock" ] || [ -f "Cargo.toml" ]; then echo "rust"
    elif [ -f "go.mod" ]; then echo "go"
    elif [ -f "package.json" ]; then echo "typescript"
    else echo "unknown"; fi
}

LANG=$(detect_language)
LANG_SCRIPT="${SCRIPT_DIR}/languages/${LANG}/validate-architecture.sh"
CONSISTENCY_SCRIPT="${SCRIPT_DIR}/check_language_consistency.sh"

# Language consistency runs for EVERY language (architecture docs must use the
# project language — catches scaffold stubs emitted in the wrong language).
run_consistency() {
    if [ -f "$CONSISTENCY_SCRIPT" ]; then
        bash "$CONSISTENCY_SCRIPT" || CONSISTENCY_RC=1
        echo ""
    fi
}

if [ -f "$LANG_SCRIPT" ]; then
    bash "$LANG_SCRIPT" "$@"
    LANG_RC=$?
    CONSISTENCY_RC=0
    run_consistency
    [ "$LANG_RC" -ne 0 ] && exit "$LANG_RC"
    [ "${CONSISTENCY_RC:-0}" -ne 0 ] && exit 1
    exit 0
else
    echo "No architecture validator for language: C.UTF-8"
    CONSISTENCY_RC=0
    run_consistency
    exit "${CONSISTENCY_RC:-0}"
fi
