#!/usr/bin/env bash
# ============================================================================
# prove_mandate_contracts.sh — deterministic proof that the Mandate contracts hold
# ============================================================================
# Issue: "Proofing: Validation scripts + CI integration" (epic: mandate)
#
# Every check is a grep/AST-free assertion over the working tree: zero tokens, no
# LLM, runs in CI and locally. Each contract named in the module doc gets at least
# one check, and each check is written so that *removing the implementation* makes
# it fail (that is the acceptance criterion "scripts fail if implementation is
# removed").
#
# Usage: bash .pi/scripts/ci/prove_mandate_contracts.sh [--root <dir>]
# Exit:  0 all contracts proven; 1 at least one broken
# ============================================================================
set -uo pipefail

ROOT="$(pwd)"
if [ "${1:-}" = "--root" ] && [ -n "${2:-}" ]; then ROOT="$2"; fi
cd "$ROOT" || exit 1

GREEN='\033[0;32m'; RED='\033[0;31m'; NC='\033[0m'
PASS=0; FAIL=0
pass() { echo -e "${GREEN}✅ PASS${NC} $1"; PASS=$((PASS+1)); }
fail() { echo -e "${RED}❌ FAIL${NC} $1"; FAIL=$((FAIL+1)); }

echo "============================================"
echo "  Mandate contract proofs"
echo "============================================"

# ── 1. every frozen component still exists where the contract says ──────────
echo ""
echo "--- Layout (contract v1) ---"
REQUIRED=(
  "src/mandate/domain/values.py|BankDigest|Cap|Threshold|PartyRef|Eligibility|PayeeStatus"
  "src/mandate/domain/errors.py|OwnerActionRequired|OwnerProofInvalid|ThresholdExceedsCap|ConstitutionCorrupted"
  "src/mandate/domain/events.py|PayeeRegistered|PayeeQuarantined|PayeeFrozen|PayeeReapproved"
  "src/mandate/domain/repositories.py|HouseholdRepository|ConstitutionRepository|PayeeRepository"
  "src/mandate/domain/ports.py|OwnerSignatureProof|EligibilityResolver"
  "src/mandate/domain/payee.py|class Payee"
  "src/mandate/domain/constitution.py|class Constitution"
  "src/mandate/domain/household.py|class Household"
  "src/mandate/domain/services.py|EligibilityResolver"
  "src/mandate/application/dto.py|CreateMandateCommand|RegisterPayeeCommand"
  "src/mandate/application/services.py|CreateMandate|RegisterPayee|FreezePayee"
  "src/mandate/infrastructure/repositories.py|HouseholdRepository|PayeeRepository"
  "src/mandate/interfaces/http/router.py|presented-digest|eligibility"
)
for entry in "${REQUIRED[@]}"; do
  file="${entry%%|*}"
  needles="${entry#*|}"
  if [ ! -f "$file" ]; then fail "missing $file"; continue; fi
  missing=""
  IFS='|' read -ra NEEDLE_LIST <<< "$needles"
  for needle in "${NEEDLE_LIST[@]}"; do
    grep -q -- "$needle" "$file" || missing="$missing $needle"
  done
  if [ -n "$missing" ]; then fail "$file lost:${missing}"; else pass "$file"; fi
done

# ── 2. the six catalog application services are implemented, not just declared ──
echo ""
echo "--- Catalog application services implemented ---"
for service in CreateMandate PublishConstitutionVersion RegisterPayee QuarantinePayee ReapprovePayeeDigest FreezePayee; do
  if grep -q "class ${service}Service" src/mandate/application/services_impl.py 2>/dev/null \
     && grep -q "async def execute" src/mandate/application/services_impl.py; then
    pass "${service} implemented"
  else
    fail "${service} has no implementation"
  fi
done

# ── 3. no repository manages transactions (ADR-002 / txn-placement) ─────────
echo ""
echo "--- Transaction placement ---"
if grep -qE "\.commit\(\)|\.rollback\(\)|begin_nested" src/mandate/infrastructure/repositories.py 2>/dev/null; then
  fail "a repository manages its own transaction; only application/ may"
else
  pass "repositories participate, never commit"
fi
if grep -q "session_scope" src/mandate/application/services_impl.py 2>/dev/null; then
  pass "application services own the unit of work"
else
  fail "application services do not open a unit of work"
fi

# ── 4. the domain stays framework-free (dip-domain) ────────────────────────
echo ""
echo "--- Domain purity ---"
if grep -rEq "^\s*(import|from)\s+(fastapi|sqlalchemy|starlette|uvicorn|httpx)" src/mandate/domain/*.py 2>/dev/null; then
  fail "domain/ imports a framework"
else
  pass "domain/ imports no framework"
fi

# ── 5. invariant anchors are present in code, not only in docs ─────────────
echo ""
echo "--- Invariant anchors ---"
prove() { # file, pattern, label
  if grep -qE "$2" "$1" 2>/dev/null; then pass "$3"; else fail "$3 (pattern missing in $1)"; fi
}
# Patterns name the *assignment* or *raise*, not the concept: a mutation that deletes the state
# transition must turn this red, otherwise the proof is decorative.
prove src/mandate/domain/payee.py "self\.status = PayeeStatus\.FROZEN" "P-4 freeze transition exists"
prove src/mandate/domain/payee.py "self\.status = PayeeStatus\.QUARANTINED" "P-2 quarantine transition exists"
prove src/mandate/domain/payee.py "raise OwnerActionRequired" "P-1/P-3 owner-only guard"
prove src/mandate/domain/payee.py "raise OwnerProofInvalid" "P-3/P-5 proof required to re-approve"
prove src/mandate/domain/constitution.py "raise ConstitutionCorrupted" "H-4 corruption is detected"
prove src/mandate/domain/constitution.py "raise ThresholdExceedsCap" "H-6 threshold <= cap enforced"
prove src/mandate/domain/constitution.py "\.supersede\(\)" "H-7 supersession exists"
prove src/mandate/domain/household.py "raise OwnerActionRequired" "H-3 non-owner refused"
prove src/mandate/domain/payee.py "self\.verified_digest = new_digest" "P-5 baseline changes only via reapprove"
prove src/mandate/infrastructure/models.py "uq_mandate_constitution_one_in_force" "H-4 enforced in storage"

# ── 6. the scam path cannot rewrite a payee address ────────────────────────
echo ""
echo "--- Scenario 2 proof (address never rewritten) ---"
if grep -qE "self\.address\s*=" src/mandate/domain/payee.py 2>/dev/null; then
  fail "Payee.address is assigned somewhere; quarantine must never move the destination"
else
  pass "no code path assigns Payee.address after construction"
fi

# ── 7. tests exist for both halves of the contract ────────────────────────
echo ""
echo "--- Test coverage of the contracts ---"
if [ -d tests/unit/mandate ]; then
  contract_tests=$(find tests/unit/mandate -name "test_*.py" | wc -l | tr -d ' ')
  [ "$contract_tests" -ge 9 ] && pass "contract tests present ($contract_tests files)" \
    || fail "expected >=9 contract test files, found $contract_tests"
else
  fail "tests/unit/mandate is missing"
fi
if [ -d tests/integration/mandate ]; then
  integration_tests=$(find tests/integration/mandate -name "test_*.py" | wc -l | tr -d ' ')
  [ "$integration_tests" -ge 2 ] && pass "integration tests present ($integration_tests files)" \
    || fail "expected >=2 integration test files, found $integration_tests"
else
  fail "tests/integration/mandate is missing"
fi
for pair in "src/mandate/domain/payee.py:tests/unit/mandate/behaviour/test_payee_behaviour.py" \
            "src/mandate/domain/constitution.py:tests/unit/mandate/behaviour/test_rules_behaviour.py" \
            "src/mandate/infrastructure/repositories.py:tests/integration/mandate/test_repositories.py" \
            "src/mandate/interfaces/http/router.py:tests/integration/mandate/test_http_api.py"; do
  impl="${pair%%:*}"; test="${pair##*:}"
  if [ -f "$impl" ] && [ -f "$test" ]; then pass "${impl##*/} has a test"; else fail "${impl} is untested"; fi
done

# ── 8. wiring: the context is installed in a real app shell ───────────────
echo ""
echo "--- Runtime wiring (ADR-009) ---"
if grep -q "mandate" src/apps/console_api/app.py 2>/dev/null; then
  pass "Mandate is installed in the console-api composition root"
else
  fail "Mandate is implemented but not installed in any app shell"
fi
# The E2E proof is a test that drives the installed router through the public app
# (`console_api.app.build`), not the application services directly.
if grep -rq "console_api.app import build" tests/ 2>/dev/null \
   && grep -rq "/v1/payees/" tests/integration/mandate 2>/dev/null; then
  pass "an end-to-end test exercises the wired path"
else
  fail "no end-to-end test exercises the wired path"
fi

echo ""
echo "============================================"
echo "  Passed: ${PASS}   Failed: ${FAIL}"
echo "============================================"
[ "$FAIL" -eq 0 ] || exit 1
