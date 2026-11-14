#!/usr/bin/env bash
# ============================================================================
# check_billing_contracts.sh — deterministic Billing contract proofing
# ============================================================================
# Proves the frozen Billing contract (docs/contracts/billing-contract-freeze.md)
# still has a concrete implementation, tests, storage mirrors and a runtime
# registration. Zero tokens, runs on every build.
#
# What it asserts:
#   1. the frozen contract artifact still exists;
#   2. every frozen interface has a concrete implementation class;
#   3. every application service is reachable from the HTTP composition root;
#   4. the storage mirrors of B-1/B-3 exist in the migration;
#   5. every Billing invariant B-1…B-7 is named by at least one test;
#   6. the domain layer imports no web/ORM framework;
#   7. the context is installed in the console-api composition root.
#
# This is a negative test by construction: delete a concrete class, a test, a
# migration index or the router registration and the corresponding check fails.
#
# Usage: bash .pi/scripts/ci/check_billing_contracts.sh [--root <dir>]
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
echo "  Billing Contract Proofing"
echo "============================================"

# ── 1. Frozen contract + implementation surface ─────────────────────────────
echo ""
echo "--- Contract artifacts ---"
require_file "docs/contracts/billing-contract-freeze.md"
require_file ".pi/architecture/modules/billing.md"
require_file "src/billing/domain/values.py"
require_file "src/billing/domain/invoice.py"
require_file "src/billing/domain/payment_attempt.py"
require_file "src/billing/domain/repositories.py"
require_file "src/billing/application/services_impl.py"
require_file "src/billing/infrastructure/repositories.py"
require_file "src/billing/infrastructure/models.py"
require_file "src/billing/interfaces/http/router.py"
require_file "migrations/versions/002_billing.py"

# ── 2. Every frozen interface has a concrete implementation ─────────────────
echo ""
echo "--- Interface → implementation ---"
require_symbol "class RecordInvoiceService(RecordInvoice)" "src/billing/application/services_impl.py"
require_symbol "class ProposePaymentService(ProposePayment)" "src/billing/application/services_impl.py"
require_symbol "class SettleInvoiceService" "src/billing/application/services_impl.py"
require_symbol "class ApplyDeterminationService" "src/billing/application/services_impl.py"
require_symbol "class SqlInvoiceRepository(InvoiceRepository)" "src/billing/infrastructure/repositories.py"
require_symbol "class SqlPaymentAttemptRepository(PaymentAttemptRepository)" "src/billing/infrastructure/repositories.py"
require_symbol "class OutboxWriter" "src/billing/infrastructure/repositories.py"
require_symbol "class InvoiceHash(ValueObject)" "src/billing/domain/values.py"
require_symbol "class BilledAmount(ValueObject)" "src/billing/domain/values.py"
require_symbol "FORBIDDEN_PROPOSAL_KEYS" "src/billing/domain/payment_attempt.py"
require_symbol "class DigestReviewPort(Protocol)" "src/billing/domain/ports.py"
require_symbol "class InvoiceDocumentParser(Protocol)" "src/billing/domain/ports.py"

# ── 3. Every application service is registered at the composition seam ──────
echo ""
echo "--- Runtime registration ---"
for service in record_invoice propose_payment list_invoices get_invoice get_attempt; do
    require_symbol "\"$service\"" "src/billing/interfaces/http/router.py"
done

# ── 4. Storage mirrors of the invariants ───────────────────────────────────
echo ""
echo "--- Persistence contract ---"
require_symbol "uq_billing_invoices_hash" "migrations/versions/002_billing.py"
require_symbol "uq_billing_attempts_one_active" "migrations/versions/002_billing.py"
require_symbol "billing_outbox" "migrations/versions/002_billing.py"

# ── 5. Every invariant is named by at least one suite ──────────────────────
echo ""
echo "--- Invariant coverage ---"
TEST_DIRS=("tests/unit/billing" "tests/integration/billing")
for invariant in B-1 B-2 B-3 B-4 B-5 B-6 B-7; do
    if grep -RqF "$invariant" "${TEST_DIRS[@]}" 2>/dev/null; then
        pass "$invariant is asserted by a suite"
    else
        fail "$invariant has no test (the invariant is unproven)"
    fi
done

# ── 6. Domain layer purity (AC #8) ─────────────────────────────────────────
echo ""
echo "--- Layer purity ---"
if grep -REn "^\s*(from|import)\s+(fastapi|sqlalchemy|httpx|flask|django)" src/billing/domain/ >/dev/null 2>&1; then
    fail "src/billing/domain imports a web/ORM framework"
else
    pass "src/billing/domain imports no FastAPI/SQLAlchemy/httpx"
fi

# ── 7. Composition root registration ───────────────────────────────────────
echo ""
echo "--- Composition root ---"
if grep -q "billing.interfaces.http" src/apps/console_api/app.py 2>/dev/null \
    && grep -q "billing," src/apps/console_api/app.py 2>/dev/null; then
    pass "Billing is installed in console-api"
else
    fail "Billing is not registered in src/apps/console_api/app.py"
fi

# ── Summary ────────────────────────────────────────────────────────────────
echo ""
echo "============================================"
echo -e "  Passed: ${GREEN}${PASS}${NC}  Failed: ${RED}${FAIL}${NC}"
if [[ "$FAIL" -gt 0 ]]; then
    echo "billing contract proofing FAILED"
    exit 1
fi
echo "billing contract proofing passed"
exit 0
