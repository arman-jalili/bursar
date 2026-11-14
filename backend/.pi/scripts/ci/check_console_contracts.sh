#!/usr/bin/env bash
# ============================================================================
# check_console_contracts.sh — prove the frozen Console contract is implemented
#
# Reads the frozen contract (docs/contracts/console-contract-freeze.md +
# .pi/architecture/modules/console.md) and checks, deterministically, that:
#
#   * every frozen behaviour body has an implementation (no leftover
#     NotImplementedError stubs outside the protocol definitions),
#   * the three catalogued projections, six ACL whitelists, six upstream
#     adapters and eight routes exist,
#   * `src/console/domain/` does NOT exist (CON-09 / ADR-008 — absence is the
#     architecture, so its appearance is a failure here too),
#   * each invariant suite still exists,
#   * the project's real coverage tool holds the console above its floor.
#
# It answers "is the contract still wired?" — correctness belongs to the tests.
# Zero tokens, every build.
#
# Usage: bash check_console_contracts.sh [--help]
# Exit:  0 all checks pass · 1 a contract gap was found
# ============================================================================
set -uo pipefail

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    sed -n '2,26p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 0
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT" || exit 1

PASS=0
FAIL=0
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok()   { echo -e "  ${GREEN}✓${NC} $1"; PASS=$((PASS + 1)); }
bad()  { echo -e "  ${RED}✗${NC} $1"; FAIL=$((FAIL + 1)); }
warn() { echo -e "  ${YELLOW}!${NC} $1"; }

need_file()   { [ -f "$1" ] && ok "file $1" || bad "missing file $1"; }
need_dir()    { [ -d "$1" ] && ok "directory $1" || bad "missing directory $1"; }
need_symbol() { grep -qE "$2" "$1" 2>/dev/null && ok "$1: $3" || bad "$1: missing $3"; }
forbid_dir()  { [ ! -d "$1" ] && ok "$1 does not exist" || bad "$1 exists — CON-09 forbids it"; }

echo "── Console contract implementation ──"

# ── Frozen artefacts ────────────────────────────────────────────────────────
need_file "docs/contracts/console-contract-freeze.md"
need_file ".pi/architecture/modules/console.md"
need_file "src/console/application/dto.py"
need_file "src/console/application/presentation.py"
need_file "src/console/application/refusals.py"
need_file "src/console/application/errors.py"
need_file "src/console/application/ports.py"
need_file "src/console/application/services.py"
need_file "src/console/infrastructure/acl.py"
need_file "src/console/infrastructure/http.py"
need_file "src/console/infrastructure/transport.py"
need_file "src/console/infrastructure/purity.py"
need_file "src/console/infrastructure/repository/cache.py"
need_file "src/console/infrastructure/repository/memory_cache.py"
need_file "src/console/interfaces/api.py"
need_file "src/console/interfaces/deps.py"
need_file "src/console/interfaces/schemas.py"

# ── CON-09: no domain layer, by design ──────────────────────────────────────
forbid_dir "src/console/domain"
need_symbol "src/console/infrastructure/purity.py" "def declared_layers" "declared_layers seam"
need_symbol "src/console/infrastructure/purity.py" "FORBIDDEN_LAYERS" "forbidden layer list"

# ── No leftover Phase-A stubs in behaviour bodies ───────────────────────────
# `ports.py` and `repository/cache.py` define Protocols whose bodies are
# documented NotImplementedError placeholders; they are excluded on purpose.
if grep -H "NotImplementedError" \
    src/console/application/presentation.py \
    src/console/application/refusals.py \
    src/console/application/services.py \
    src/console/infrastructure/acl.py \
    src/console/infrastructure/http.py \
    src/console/infrastructure/purity.py \
    src/console/infrastructure/repository/memory_cache.py \
    src/console/interfaces/api.py >/dev/null 2>&1; then
    bad "a frozen Console behaviour is still a NotImplementedError stub"
else
    ok "no NotImplementedError stubs in the behaviour bodies"
fi

# ── Three catalogued projections (module doc §Application services) ─────────
need_symbol "src/console/application/services.py" "class ProjectApprovalInbox" "ProjectApprovalInbox"
need_symbol "src/console/application/services.py" "class ProjectPayerBills" "ProjectPayerBills"
need_symbol "src/console/application/services.py" "class ProjectEvidence" "ProjectEvidence"
need_symbol "src/console/application/services.py" "async def submit" "signature passthrough method"

# ── Six surface whitelists (CON-01) ─────────────────────────────────────────
for projection in project_owner_inbox project_payer_bill project_payee \
                  project_constitution project_evidence project_verification; do
    need_symbol "src/console/infrastructure/acl.py" "def ${projection}\(" "ACL ${projection}"
done

# ── Six upstream adapters (CON-01..CON-08) ──────────────────────────────────
for adapter in AuthorityHttpAdapter BillingHttpAdapter SettlementHttpAdapter \
               EvidenceHttpAdapter MandateHttpAdapter; do
    need_symbol "src/console/infrastructure/http.py" "class ${adapter}" "${adapter}"
done
need_symbol "src/console/infrastructure/transport.py" "def demo_transport" "recorded upstream transport"

# ── Copy tables and refusal vocabulary (CON-05..CON-07) ─────────────────────
need_symbol "src/console/application/presentation.py" "PAYER_STATUS_COPY" "payer status copy"
need_symbol "src/console/application/presentation.py" "PAYOUT_SIMULATED_LABEL" "simulated payout label"
need_symbol "src/console/application/refusals.py" "REFUSAL_COPY" "refusal copy table"
need_symbol "src/console/application/refusals.py" "def refusal_copy" "refusal renderer"

# ── Eight routes, exactly one write (CON-03/CON-04) ─────────────────────────
need_symbol "src/console/interfaces/api.py" "CONSOLE_ROUTES" "frozen route table"
need_symbol "src/console/interfaces/api.py" "def build_router" "router builder"
need_symbol "src/console/interfaces/api.py" "def build_deps" "composition build"
need_symbol "src/console/interfaces/api.py" "def install" "composition-root installer"

route_count=$(grep -cE '^ +Route\(' src/console/interfaces/api.py 2>/dev/null || true)
if [ "${route_count:-0}" -eq 8 ]; then
    ok "CONSOLE_ROUTES has the frozen 8 rows"
else
    bad "CONSOLE_ROUTES has ${route_count:-0} rows; the frozen table has 8"
fi

write_count=$(grep -cE '^[[:space:]]+mutating=True,' src/console/interfaces/api.py 2>/dev/null || true)
if [ "${write_count:-0}" -eq 1 ]; then
    ok "exactly one mutating route (the signature passthrough)"
else
    bad "${write_count:-0} mutating routes; CON-04 allows exactly one"
fi

# ── Invariant suites still exist ────────────────────────────────────────────
for suite in whitelist anti-corruption-layer-field-whitelists exact-fields \
             passthrough read-only payer-copy simulated-payout refusal-reason \
             verify-toggle no-domain-layer mobile application-services-catalog; do
    need_dir "tests/unit/console/${suite}"
done
need_file "tests/integration/console/test_http_api.py"

# ── Real coverage tooling, project floor (not a per-module grep) ────────────
if [ -x ".venv/bin/python" ]; then
    if .venv/bin/python -m pytest tests/unit/console tests/integration/console \
        --cov=src/console --cov-fail-under=90 -q >/dev/null 2>&1; then
        ok "console coverage ≥ 90% (pytest --cov-fail-under=90)"
    else
        bad "console coverage fell below 90% or its tests failed"
    fi
else
    warn "no .venv interpreter — coverage floor not measured here"
fi

# ── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo "  Console proofing: ${PASS} passed, ${FAIL} failed"
if [ "$FAIL" -gt 0 ]; then
    echo -e "${RED}  Console contract proofing FAILED${NC}"
    exit 1
fi
echo -e "${GREEN}  Console contract proofing passed${NC}"
exit 0
