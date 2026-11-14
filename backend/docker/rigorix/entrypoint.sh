#!/bin/sh
# The runtime root is a volume (or a bind mount on the host), so it starts empty: seed the host
# config there once. The preconditions file is written by the operator (scripts/setup-preconditions.sh)
# into the same directory and must never be overwritten here.
set -eu

mkdir -p /workspace/.rigorix/audit

if [ ! -f /workspace/.rigorix/rigorix.toml ]; then
  cp /opt/rigorix/rigorix.toml /workspace/.rigorix/rigorix.toml
fi

exec "$@"
