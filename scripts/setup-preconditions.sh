#!/usr/bin/env bash
# Install the operator-owned precondition and arm it in Rigorix's runtime root.
#
# The check and the authority live under /tmp/bursar-preconditions — outside the repository and
# outside the console's application code. Rigorix invokes the check at dispatch time, after any
# approval, immediately before the governed step would run.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIR="${BURSAR_PRECONDITION_DIR:-/tmp/bursar-preconditions}"
RUNTIME="${RIGORIX_RUNTIME_DIR:-$ROOT/.rigorix-runtime}"

mkdir -p "$DIR" "$RUNTIME/.rigorix"

cat > "$DIR/check-payee.mjs" <<'JS'
#!/usr/bin/env node
// The whole authority: is this payee allowed to be paid right now?
// Reads the step's parameters on stdin, the operator's status file next to itself.
// 0 = authorized, 3 = frozen/unknown, 4 = the check itself is broken.
import { readFileSync } from "node:fs";

let input = {};
try {
  input = JSON.parse(readFileSync(0, "utf8"));
} catch {
  console.error("precondition: no stdin — refusing (fail closed)");
  process.exit(4);
}

const address = String(input.parameters?.payee_address ?? "").toLowerCase();
if (!address) {
  console.error("precondition: no payee_address on the step — refusing (fail closed)");
  process.exit(4);
}

let authority;
try {
  authority = JSON.parse(readFileSync(new URL("./authority.json", import.meta.url), "utf8"));
} catch {
  console.error("precondition: no readable authority.json — refusing (fail closed)");
  process.exit(4);
}

const status = authority[address] ?? "unknown";
console.error(`precondition: ${address} is ${status}`);
process.exit(status === "active" ? 0 : 3);
JS
chmod +x "$DIR/check-payee.mjs"

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
# Armed by scripts/setup-preconditions.sh. The check and authority live OUTSIDE the repo.
[[preconditions]]
id = "payee-authorized"
match = { tool = "run_command", params = [{ pointer = "/command", kind = "glob", value = "*payments.broadcast*" }] }
require_params = ["/command", "/payee_address"]
command = ["$DIR/check-payee.mjs"]
timeout_ms = 5000
failure = "deny"
authority_path = "$DIR/authority.json"
TOML

echo "precondition installed: $DIR/check-payee.mjs"
echo "authority:             $DIR/authority.json"
echo "gate config:           $RUNTIME/.rigorix/preconditions.toml"
echo "restart rigorix-server to arm the gate (the authority file is read live)."
