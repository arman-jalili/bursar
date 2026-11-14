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
RUNTIME_DIR="${RIGORIX_RUNTIME_DIR:-$ROOT/.rigorix-runtime}"

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
# The signed trail lives under the repo so the console container can read it read-only.
mkdir -p "$RUNTIME_DIR/.rigorix/audit"
if [[ ! -f "$RUNTIME_DIR/.rigorix/rigorix.toml" ]]; then
  cp "$ROOT/backend/docker/rigorix/rigorix.toml" "$RUNTIME_DIR/.rigorix/rigorix.toml"
fi
export RIGORIX_REPO_ROOT="$RUNTIME_DIR"

echo "rigorix-server on $RIGORIX_SERVER_BIND (sandbox=$RIGORIX_SANDBOX, broadcaster=$VENV_BIN)"
exec "$BIN"
