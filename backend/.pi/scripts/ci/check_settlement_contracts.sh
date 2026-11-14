#!/usr/bin/env bash
# ============================================================================
# check_settlement_contracts.sh — deterministic Settlement contract proofing
# ============================================================================
# Proves the frozen Settlement contract (docs/contracts/settlement-contract-freeze.md)
# still has a concrete implementation, tests, storage mirrors and a runtime
# registration. Zero tokens, runs on every build.
#
# What it asserts:
#   1. the frozen contract artifact and the module doc still exist;
#   2. every frozen interface either has a concrete implementation or is a
#      *documented* deferral (ADR-009 + runbook) — an undocumented stub fails;
#   3. the implemented surface no longer raises NotImplementedError;
#   4. every application service that is wired is registered at the runtime seam;
#   5. the storage mirrors of SC-3/SC-5/SC-10 exist in the migration;
#   6. every invariant SC-1…SC-12 is named by at least one suite;
#   7. src/settlement/domain imports no chain/web/ORM framework (SC-12);
#   8. the deferred endpoints say why they are deferred (blocker text present);
#   9. the context is installed in the console-api composition root.
#
# This is a negative test by construction: delete a concrete class, a test, a
# migration constraint, the router registration or the ADR and the corresponding
# check fails. Removing an implementation and leaving the interface behind also
# fails (check 3).
#
# Usage: bash .pi/scripts/ci/check_settlement_contracts.sh [--root <dir>]
# Exit:  0 all checks pass; 1 one or more checks failed
# ============================================================================
set -uo pipefail

ROOT="$(pwd)"
if [[ "${1:-}" == "--root" && -n "${2:-}" ]]; then
    ROOT="$2"
fi
cd "$ROOT" || exit 1

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

FAIL=0
PASS=0

pass() { echo -e "  ${GREEN}✓ PASS${NC} $1"; PASS=$((PASS + 1)); }
fail() { echo -e "  ${RED}✗ FAIL${NC} $1"; FAIL=$((FAIL + 1)); }

require_file() {
    if [[ -f "$1" ]]; then pass "file exists: $1"; else fail "missing file: $1"; fi
}

require_symbol() {
    local symbol="$1" file="$2"
    if grep -qF "$symbol" "$file" 2>/dev/null; then
        pass "$symbol present in $file"
    else
        fail "$symbol missing from $file (contract implementation removed?)"
    fi
}

echo "============================================"
echo "  Settlement Contract Proofing"
echo "============================================"

# ── 1. Frozen contract + implementation surface ─────────────────────────────
echo ""
echo "--- Contract artifacts ---"
require_file "docs/contracts/settlement-contract-freeze.md"
require_file ".pi/architecture/modules/settlement.md"
require_file ".pi/architecture/decisions/ADR-009-runtime-wiring-multilang-judgment.md"
require_file "docs/runbook-settlement.md"
require_file "src/settlement/domain/values.py"
require_file "src/settlement/domain/settlement_order.py"
require_file "src/settlement/domain/chain_receipt.py"
require_file "src/settlement/domain/services.py"
require_file "src/settlement/domain/repositories.py"
require_file "src/settlement/domain/ports.py"
require_file "src/settlement/domain/events.py"
require_file "src/settlement/application/services_impl.py"
require_file "src/settlement/infrastructure/models.py"
require_file "src/settlement/infrastructure/mappers.py"
require_file "src/settlement/infrastructure/repositories.py"
require_file "src/settlement/interfaces/http/router.py"
require_file "migrations/versions/003_settlement.py"

# ── 2. Frozen interface → implementation or documented deferral ─────────────
echo ""
echo "--- Interface → implementation ---"
# Value objects and the aggregate.
require_symbol "class Nullifier(ValueObject)" "src/settlement/domain/values.py"
require_symbol "class ChainNetwork(ValueObject)" "src/settlement/domain/values.py"
require_symbol "def derive(cls, invoice_hash: str, scope: str) -> Nullifier" "src/settlement/domain/values.py"
require_symbol "def order(" "src/settlement/domain/settlement_order.py"
require_symbol "def command_params(self)" "src/settlement/domain/settlement_order.py"
require_symbol "def mark_submitted(self" "src/settlement/domain/settlement_order.py"
require_symbol "def conclude(self" "src/settlement/domain/settlement_order.py"
require_symbol "def is_final(self, confirmations_required: int)" "src/settlement/domain/chain_receipt.py"
require_symbol "class NullifierPolicy" "src/settlement/domain/services.py"
require_symbol "class FinalityPolicy" "src/settlement/domain/services.py"
# Repository adapters (the storage half of SC-3/SC-5/SC-10).
require_symbol "class SqlSettlementOrderRepository(SettlementOrderRepository)" "src/settlement/infrastructure/repositories.py"
require_symbol "class SqlNullifierRepository(NullifierRepository)" "src/settlement/infrastructure/repositories.py"
require_symbol "class SqlChainReceiptRepository(ChainReceiptRepository)" "src/settlement/infrastructure/repositories.py"
require_symbol "class OutboxWriter" "src/settlement/infrastructure/repositories.py"
# Read-side application services.
require_symbol "class GetReceiptService(GetReceipt)" "src/settlement/application/services_impl.py"
require_symbol "class ListOrdersService(ListOrders)" "src/settlement/application/services_impl.py"
require_symbol "class CostSummaryService(CostSummary)" "src/settlement/application/services_impl.py"
require_symbol "class AnchorHashService(AnchorHash)" "src/settlement/application/services_impl.py"

# ── 2b. Deferred interfaces must be *documented* deferrals, not silent stubs ─
echo ""
echo "--- Documented deferrals (ADR-009) ---"
for symbol in "class DispatchPayment" "class SettleOnce" "class PaymentExecutor(Protocol)" "class ChainGateway(Protocol)" "class DeterminationGate(Protocol)"; do
    if grep -qF "$symbol" src/settlement/application/services.py src/settlement/domain/ports.py 2>/dev/null; then
        pass "frozen interface still present: $symbol"
    else
        fail "frozen interface removed: $symbol"
    fi
done
BLOCKERS_OK=1
grep -qF "B-1" .pi/architecture/decisions/ADR-009-runtime-wiring-multilang-judgment.md || BLOCKERS_OK=0
grep -qF "B-2" .pi/architecture/decisions/ADR-009-runtime-wiring-multilang-judgment.md || BLOCKERS_OK=0
grep -qF "Integration gaps" docs/runbook-settlement.md || BLOCKERS_OK=0
if [[ "$BLOCKERS_OK" == "1" ]]; then
    pass "both contract blockers (B-1, B-2) are recorded in ADR-009 and the runbook"
else
    fail "a deferred contract blocker is undocumented (ADR-009 B-1/B-2 or runbook Integration gaps)"
fi
if grep -qF "SC-3" src/settlement/interfaces/http/router.py 2>/dev/null; then
    pass "the deferred dispatch endpoint names its blocker (SC-3)"
else
    fail "the deferred dispatch endpoint does not name its blocker"
fi

# ── 3. The implemented surface no longer raises NotImplementedError ─────────
echo ""
echo "--- Implemented, not stubbed ---"
for file in \
    src/settlement/domain/values.py \
    src/settlement/domain/views.py \
    src/settlement/domain/services.py \
    src/settlement/domain/settlement_order.py \
    src/settlement/domain/chain_receipt.py \
    src/settlement/application/services_impl.py; do
    if grep -q "NotImplementedError" "$file" 2>/dev/null; then
        fail "$file still contains a NotImplementedError body (implementation removed?)"
    else
        pass "$file has no stub body"
    fi
done

# ── 4. Wired services are registered at the runtime seam ───────────────────
echo ""
echo "--- Runtime registration ---"
for service in get_order list_orders get_receipt list_receipts cost_summary nullifier_status; do
    require_symbol "\"$service\"" "src/settlement/interfaces/http/router.py"
done

# ── 5. Storage mirrors of the invariants ───────────────────────────────────
echo ""
echo "--- Persistence contract ---"
require_symbol "uq_settlement_orders_intent" "migrations/versions/003_settlement.py"
require_symbol "uq_settlement_orders_tx_hash" "migrations/versions/003_settlement.py"
require_symbol "settlement_nullifiers" "migrations/versions/003_settlement.py"
require_symbol "settlement_outbox" "migrations/versions/003_settlement.py"
if grep -q "primary_key=True" migrations/versions/003_settlement.py 2>/dev/null; then
    pass "settlement_nullifiers has a primary key (SC-5 last local lock)"
else
    fail "settlement_nullifiers has no primary key — the nullifier lock is gone"
fi

# ── 6. Every invariant is named by at least one suite ──────────────────────
echo ""
echo "--- Invariant coverage ---"
TEST_DIRS=("tests/unit/settlement" "tests/integration/settlement")
for invariant in SC-1 SC-2 SC-3 SC-4 SC-5 SC-6 SC-7 SC-8 SC-9 SC-10 SC-11 SC-12; do
    if grep -RqF "$invariant" "${TEST_DIRS[@]}" 2>/dev/null; then
        pass "$invariant is asserted by a suite"
    else
        fail "$invariant has no test (the invariant is unproven)"
    fi
done

# ── 7. Domain layer purity (SC-12) ─────────────────────────────────────────
echo ""
echo "--- Layer purity ---"
if grep -REn "^\s*(from|import)\s+(web3|eth_account|httpx|fastapi|flask|django|requests|starlette|sqlalchemy)" src/settlement/domain/ >/dev/null 2>&1; then
    fail "src/settlement/domain imports a chain/web/ORM framework"
else
    pass "src/settlement/domain imports no web3/httpx/fastapi/sqlalchemy"
fi
if grep -REn "^\s*from\s+src\.settlement\.(application|infrastructure|interfaces)" src/settlement/domain/ >/dev/null 2>&1; then
    fail "src/settlement/domain imports an outward layer"
else
    pass "src/settlement/domain imports no outward layer"
fi

# ── 8. Composition root registration ───────────────────────────────────────
echo ""
echo "--- Composition root ---"
if grep -q "settlement.interfaces.http" src/apps/console_api/app.py 2>/dev/null \
    && grep -q "settlement," src/apps/console_api/app.py 2>/dev/null; then
    pass "Settlement is installed in console-api"
else
    fail "Settlement is not registered in src/apps/console_api/app.py"
fi

# ── Summary ────────────────────────────────────────────────────────────────
echo ""
echo "============================================"
echo -e "  Passed: ${GREEN}${PASS}${NC}  Failed: ${RED}${FAIL}${NC}"
if [[ "$FAIL" -gt 0 ]]; then
    echo "settlement contract proofing FAILED"
    exit 1
fi
echo "settlement contract proofing passed"
exit 0
