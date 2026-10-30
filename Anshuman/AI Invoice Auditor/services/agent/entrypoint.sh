#!/bin/sh
set -e

# Bind-mounted host dirs come in owned by the host user, which blocks writes by
# the unprivileged container user. Fix ownership at startup, then drop privileges.
chown -R appuser:appuser /app/outputs /app/data 2>/dev/null || true

exec gosu appuser "$@"
