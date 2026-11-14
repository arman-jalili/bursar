#!/usr/bin/env bash
# Install the operator-owned dispatch checks and arm them in Rigorix's runtime root.
#
# These are the checks Rigorix's gate runs immediately before `payments.broadcast`:
#
#   approval-valid      above the line, the intent carries the owner's signature
#   payee-authorized    the operator has not frozen this payee
#   capacity-available  the amount still fits the daily cap (and claims it atomically)
#
# The check, the ledger endpoint and the authority file live under $BURSAR_PRECONDITION_DIR —
# outside the repository. A refusal (exit 3) or a broken check (exit 4) stops the broadcast and is
# recorded in the signed envelope either way.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIR="${BURSAR_PRECONDITION_DIR:-/tmp/bursar-preconditions}"
RUNTIME="${RIGORIX_RUNTIME_DIR:-$ROOT/.rigorix-runtime}"
# The check runs inside the Rigorix execution boundary. Host-run Rigorix reaches the authority on
# the loopback; the containerized Rigorix reaches the compose/k8s Service by name.
GATE_URL="${BURSAR_GATE_URL:-http://127.0.0.1:8001}"
GATE_TOKEN="${BURSAR_GATE_TOKEN:-demo-owner-token}"

mkdir -p "$DIR" "$RUNTIME/.rigorix"

# Shared by all three checks: load stdin, load gate.json. Kept inline so each script is standalone.
read -r -d '' GATE_HEADER <<'PY' || true
import json
import sys
import urllib.request
from pathlib import Path

def fail(message):
    print(f"precondition: {message}", file=sys.stderr)
    sys.exit(4)

def gate():
    try:
        return json.loads((Path(__file__).resolve().parent / "gate.json").read_text())
    except Exception:
        fail("no readable gate.json — refusing (fail closed)")

def params():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        fail("no stdin — refusing (fail closed)")
    return payload.get("parameters") or {}

def call(method, path, body=None):
    conf = gate()
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        f"{conf['base_url'].rstrip('/')}{path}",
        data=data,
        method=method,
        headers={
            "authorization": f"Bearer {conf.get('token', '')}",
            "content-type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode())
    except Exception as exc:
        fail(f"the gate's ledger did not answer ({exc}) — refusing (fail closed)")
PY

cat > "$DIR/check-approval.py" <<PY
#!/usr/bin/env python3
"""Does this intent carry the owner's signature when the amount is above the line?"""
$GATE_HEADER

p = params()
intent_id = str(p.get("intent_id") or "")
if not intent_id:
    fail("no intent_id on the step — refusing (fail closed)")

answer = call("GET", f"/v1/gate/approval/{intent_id}")
if answer.get("granted"):
    print("precondition: approval valid", file=sys.stderr)
    sys.exit(0)
print("precondition: the owner's approval is required", file=sys.stderr)
sys.exit(3)
PY

cat > "$DIR/check-payee.py" <<'PY'
#!/usr/bin/env python3
"""Is this payee allowed to be paid right now? (the operator's freeze file)"""
import json
import sys
from pathlib import Path

try:
    payload = json.load(sys.stdin)
except Exception:
    print("precondition: no stdin — refusing (fail closed)", file=sys.stderr)
    sys.exit(4)

address = str((payload.get("parameters") or {}).get("payee_address") or "").lower()
if not address:
    print("precondition: no payee_address on the step — refusing (fail closed)", file=sys.stderr)
    sys.exit(4)

try:
    authority = json.loads((Path(__file__).resolve().parent / "authority.json").read_text())
except Exception:
    print("precondition: no readable authority.json — refusing (fail closed)", file=sys.stderr)
    sys.exit(4)

status = authority.get(address, "unknown")
print(f"precondition: {address} is {status}", file=sys.stderr)
sys.exit(0 if status == "active" else 3)
PY

cat > "$DIR/check-capacity.py" <<PY
#!/usr/bin/env python3
"""Does this payment still fit today's cap? If it does, the claim reserves it."""
$GATE_HEADER

p = params()
intent_id = str(p.get("intent_id") or "")
try:
    amount = int(p.get("amount_micro_usdc") or 0)
except (TypeError, ValueError):
    amount = 0
if not intent_id or amount <= 0:
    fail("no intent_id or amount_micro_usdc on the step — refusing (fail closed)")

answer = call(
    "POST",
    "/v1/gate/capacity",
    {"intent_id": intent_id, "amount_micro_usdc": amount},
)
if answer.get("allowed"):
    print(
        f"precondition: {amount} fits, {answer.get('headroom_micro_usdc')} still free",
        file=sys.stderr,
    )
    sys.exit(0)
print(
    f"precondition: {amount} exceeds the {answer.get('cap_micro_usdc')} cap, "
    f"{answer.get('headroom_micro_usdc')} free",
    file=sys.stderr,
)
sys.exit(3)
PY

chmod +x "$DIR/check-approval.py" "$DIR/check-payee.py" "$DIR/check-capacity.py"
rm -f "$DIR/check-payee.mjs"

cat > "$DIR/gate.json" <<JSON
{
  "base_url": "$GATE_URL",
  "token": "$GATE_TOKEN"
}
JSON

if [[ ! -f "$DIR/authority.json" ]]; then
  cat > "$DIR/authority.json" <<'JSON'
{
  "0x3c44cdddb6a900fa2b585dd299e03d12fa4293bc": "active",
  "0x15d34aaf54267db7d7c367839aaf71a00a2c6a65": "active",
  "0x90f79bf6eb2c4f870365e785982e1f101e93b906": "active",
  "0x9965507d1a55bcc2695c58ba16fb37d819b0a4dc": "active"
}
JSON
fi

cat > "$RUNTIME/.rigorix/preconditions.toml" <<TOML
# Armed by scripts/setup-preconditions.sh. The checks and their config live OUTSIDE the repo.
# Order matters: an approval refusal must not reserve capacity, and a payee refusal must not either.
[[preconditions]]
id = "approval-valid"
match = { tool = "run_command", params = [{ pointer = "/command", kind = "glob", value = "*payments.broadcast*" }] }
require_params = ["/command", "/intent_id"]
command = ["python3", "$DIR/check-approval.py"]
timeout_ms = 5000
failure = "deny"
authority_path = "$DIR/gate.json"

[[preconditions]]
id = "payee-authorized"
match = { tool = "run_command", params = [{ pointer = "/command", kind = "glob", value = "*payments.broadcast*" }] }
require_params = ["/command", "/payee_address"]
command = ["python3", "$DIR/check-payee.py"]
timeout_ms = 5000
failure = "deny"
authority_path = "$DIR/authority.json"

[[preconditions]]
id = "capacity-available"
match = { tool = "run_command", params = [{ pointer = "/command", kind = "glob", value = "*payments.broadcast*" }] }
require_params = ["/command", "/intent_id", "/amount_micro_usdc"]
command = ["python3", "$DIR/check-capacity.py"]
timeout_ms = 5000
failure = "deny"
authority_path = "$DIR/gate.json"
TOML

echo "checks installed:  $DIR/check-{approval,payee,capacity}.py"
echo "gate endpoint:     $GATE_URL"
echo "authority:         $DIR/authority.json"
echo "gate config:       $RUNTIME/.rigorix/preconditions.toml"
echo "restart rigorix-server to arm the gate (the authority file is read live)."
echo
echo "for the containerized Rigorix, run: BURSAR_GATE_URL=http://authority:8001 $0"
