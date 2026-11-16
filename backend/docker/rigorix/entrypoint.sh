#!/bin/sh
# Render the host config at the path the server actually reads (<repo_root>/rigorix.toml) on every
# boot, so a deployment can point the signed-envelope upload at the enterprise audit backend
# without baking the key into an image. The file lives inside the container; the secret stays in
# the deployment environment. The preconditions file is written by the operator into .rigorix and
# is never touched here.
set -eu
umask 077

mkdir -p /workspace/.rigorix/audit

# The audit backend is a top-level key of the host Config. Write it before any table so it does not
# become a key of [orchestrator]/[logging].
{
  if [ -n "${BURSAR_AUDIT_BACKEND_URL:-}" ]; then
    printf 'audit_backend_url = "%s"\n' "$BURSAR_AUDIT_BACKEND_URL"
    printf 'audit_backend_key = "%s"\n' "${BURSAR_AUDIT_BACKEND_KEY:-}"
  fi
  cat /opt/rigorix/rigorix.toml
} > /workspace/rigorix.toml

# Older layouts read the config from beside the audit tree; keep a seed there when absent.
if [ ! -f /workspace/.rigorix/rigorix.toml ]; then
  cp /opt/rigorix/rigorix.toml /workspace/.rigorix/rigorix.toml
fi

exec "$@"
