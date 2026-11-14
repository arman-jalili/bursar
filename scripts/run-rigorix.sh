#!/usr/bin/env bash
# Start the unmodified OSS rigorix-server on the host, with the Bursar broadcaster on its PATH.
#
# The governed dispatch step is `payments.broadcast --raw-tx <hex>`. It must exist inside the
# execution boundary Rigorix declares (RIGORIX_SANDBOX=container), so PATH here includes the
# backend virtualenv that installs the console script.
#
# Layout this expects:  <parent>/rigorix-oss  and  <parent>/proximata/bursar
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RIGORIX_DIR="${RIGORIX_OSS:-$ROOT/../../rigorix-oss}"
BIN="$RIGORIX_DIR/target/debug/rigorix-server"
VENV_BIN="$ROOT/backend/.venv/bin"

if [[ ! -x "$VENV_BIN/payments.broadcast" ]]; then
  echo "missing $VENV_BIN/payments.broadcast — run: cd backend && make install" >&2
  exit 1
fi

if [[ ! -x "$BIN" ]]; then
  echo "building $BIN (one-time; the workspace is large)…" >&2
  (cd "$RIGORIX_DIR" && cargo build -p rigorix-server)
fi

export PATH="$VENV_BIN:$PATH"
export RIGORIX_SERVER_BIND="${RIGORIX_SERVER_BIND:-0.0.0.0:3001}"
export RIGORIX_SANDBOX="${RIGORIX_SANDBOX:-container}"
export RIGORIX_HMAC_KEY="${RIGORIX_HMAC_KEY:-bursar-demo-operator-held-evidence-key-4c1f9a}"
export RIGORIX_REPO_ROOT="$RIGORIX_DIR"

echo "rigorix-server on $RIGORIX_SERVER_BIND (sandbox=$RIGORIX_SANDBOX, broadcaster=$VENV_BIN)"
exec "$BIN"
