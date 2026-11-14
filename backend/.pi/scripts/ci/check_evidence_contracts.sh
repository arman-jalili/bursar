#!/usr/bin/env bash
# ============================================================================
# check_evidence_contracts.sh — prove the frozen Evidence contract is implemented
#
# Reads the frozen contract (docs/contracts/evidence-contract-freeze.md +
# .pi/architecture/modules/evidence.md) and checks that every public interface
# has a concrete implementation, that the HTTP shape exists, and that the
# storage-level invariants (append-only, unique anchor hash) are present.
#
# This is deliberately grep-level: it answers "is the contract still wired?"
# not "is the code correct?" (the test suite answers that).
#
# Usage: bash check_evidence_contracts.sh [--help]
# Exit:  0 all checks pass · 1 a contract gap was found
# ============================================================================
set -uo pipefail

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    sed -n '2,18p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 0
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT" || exit 1

PASS=0
FAIL=0
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

ok()   { echo -e "  ${GREEN}✓${NC} $1"; PASS=$((PASS + 1)); }
bad()  { echo -e "  ${RED}✗${NC} $1"; FAIL=$((FAIL + 1)); }

need_file()    { [ -f "$1" ] && ok "file $1" || bad "missing file $1"; }
need_symbol()  { grep -qE "$2" "$1" 2>/dev/null && ok "$1: $3" || bad "$1: missing $3"; }

echo "── Evidence contract implementation ──"

need_file "docs/contracts/evidence-contract-freeze.md"
need_file ".pi/architecture/modules/evidence.md"
need_file "src/evidence/domain/evidence_envelope.py"
need_file "src/evidence/domain/anchor.py"
need_file "src/evidence/domain/values.py"
need_file "src/evidence/domain/ports.py"
need_file "src/evidence/domain/repositories.py"
need_file "src/evidence/application/dto.py"
need_file "src/evidence/application/services.py"
need_file "src/evidence/application/services_impl.py"
need_file "src/evidence/interfaces/http/router.py"
need_file "src/evidence/interfaces/subscriber.py"
need_file "migrations/versions/003_evidence.py"

# Frozen domain surface → concrete bodies (no leftover stubs).
# Frozen behaviour bodies → concrete bodies (abstract ports/repositories keep their
# documented NotImplementedError, so they are excluded).
if grep -H "NotImplementedError" \
    src/evidence/domain/evidence_envelope.py \
    src/evidence/domain/values.py \
    src/evidence/domain/anchor.py \
    src/evidence/application/services.py >/dev/null 2>&1; then
    bad "a frozen Evidence behaviour is still a NotImplementedError stub"
else
    ok "no NotImplementedError stubs in the frozen behaviour bodies"
fi

need_symbol "src/evidence/domain/evidence_envelope.py" "def canonical_bytes|def hash\(|def verify\(|def corrected\(" "envelope behaviour"
need_symbol "src/evidence/domain/values.py" "def compute\(" "EnvelopeHash.compute"
need_symbol "src/evidence/domain/anchor.py" "def matches\(" "Anchor.matches"
need_symbol "src/evidence/application/services.py" "class SealEvidence|class VerifyEvidence|class WitnessReport" "use cases"
need_symbol "src/evidence/application/dto.py" "class EnvelopeView|class SealEvidenceCommand|class VerifyEvidenceResult" "DTOs"
need_symbol "src/evidence/interfaces/subscriber.py" "class SealEventSubscriber" "runtime subscriber"

# Ports → adapters.
need_symbol "src/evidence/infrastructure/signer.py" "class HmacSigner" "EnvelopeSigner adapter"
need_symbol "src/evidence/infrastructure/anchor.py" "class SqlAnchorGateway" "AnchorGateway adapter"
need_symbol "src/evidence/infrastructure/anchor.py" "class ConfiguredAnchorPolicy" "AnchorPolicy adapter"
need_symbol "src/evidence/infrastructure/expected_events.py" "class SqlExpectedEvents" "ExpectedEventsPort adapter"
need_symbol "src/evidence/infrastructure/repositories.py" "class SqlEnvelopeRepository" "EnvelopeRepository adapter"
need_symbol "src/evidence/infrastructure/repositories.py" "class SqlAnchorRepository" "AnchorRepository adapter"
need_symbol "src/evidence/infrastructure/repositories.py" "class SqlProcessedEventRepository" "ProcessedEventRepository adapter"

# HTTP contract (concrete router, no second interface file).
need_symbol "src/evidence/interfaces/http/router.py" '"/evidence"' "GET /v1/evidence"
need_symbol "src/evidence/interfaces/http/router.py" '"/evidence/\{envelope_id\}"' "GET /v1/evidence/{id}"
need_symbol "src/evidence/interfaces/http/router.py" '"/evidence/\{envelope_id\}/verify"' "GET /v1/evidence/{id}/verify"
need_symbol "src/evidence/interfaces/http/router.py" '"/evidence/\{envelope_id\}/anchor"' "GET /v1/evidence/{id}/anchor"

# Storage invariants.
need_symbol "migrations/versions/003_evidence.py" "uq_evidence_anchors_hash" "UNIQUE(envelope_hash)"
need_symbol "migrations/versions/003_evidence.py" "BEFORE UPDATE ON" "append-only UPDATE trigger"
need_symbol "migrations/versions/003_evidence.py" "BEFORE DELETE ON" "append-only DELETE trigger"
need_symbol "src/evidence/infrastructure/models.py" "evidence_processed_events" "idempotency table"

# Composition root registration (implemented = installed).
if grep -Eq "^[[:space:]]*evidence," src/apps/console_api/app.py; then
    ok "Evidence installed in the console-api composition root"
else
    bad "Evidence is not registered in src/apps/console_api/app.py HOSTED_CONTEXTS"
fi

# Every frozen invariant has a defending suite.
for invariant in E-1 E-2 E-3 E-4 E-5 E-6 E-7 E-8 E-9 E-10 E-11; do
    if grep -rq "$invariant" tests/unit/evidence tests/integration/evidence --include='*.py'; then
        ok "invariant $invariant has a defending test"
    else
        bad "invariant $invariant has no defending test"
    fi
done

echo ""
echo "Evidence contract proof: ${PASS} passed, ${FAIL} failed"
[ "$FAIL" -eq 0 ] || exit 1
