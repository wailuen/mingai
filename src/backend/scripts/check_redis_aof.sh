#!/usr/bin/env bash
# SCHED-029: Pre-deploy check — Redis AOF persistence must be enabled.
#
# Distributed job locks (DistributedJobLock) rely on Redis SET NX EX for
# leader election. If AOF persistence is disabled, a Redis restart between
# the lock acquisition and the heartbeat renewal causes a split-brain
# condition: two pods both believe they hold the lock.
#
# This script is run as a CI pre-deploy gate and in manual deployments:
#
#   ./scripts/check_redis_aof.sh
#   ./scripts/check_redis_aof.sh redis://my-prod-redis:6379/0
#   ./scripts/check_redis_aof.sh rediss://user:password@my-prod-redis:6380/0
#
# Uses `redis-cli -u URL` (Redis CLI 6.0+) for full URL parsing that handles
# TLS (rediss://), authentication credentials, and custom ports safely without
# exposing credentials in log output.
#
# Exit codes:
#   0 — appendonly is enabled; safe to deploy
#   1 — appendonly is disabled; deployment must be blocked until fixed
#   2 — could not connect to Redis or invalid URL
#
# To enable AOF on a running instance:
#   redis-cli -u "$REDIS_URL" CONFIG SET appendonly yes
#   redis-cli -u "$REDIS_URL" BGREWRITEAOF
#   Then add "appendonly yes" to redis.conf to make it permanent.

set -euo pipefail

REDIS_URL="${1:-${REDIS_URL:-redis://localhost:6379}}"

# Validate URL scheme before use
if ! [[ "$REDIS_URL" =~ ^rediss?:// ]]; then
    echo "[check_redis_aof] ERROR: REDIS_URL must start with redis:// or rediss://" >&2
    exit 2
fi

# Redact credentials from log output (replace user:password@ with ***@)
SAFE_URL=$(echo "$REDIS_URL" | sed 's|//[^@]*@|//***@|')
echo "[check_redis_aof] Connecting to Redis at ${SAFE_URL}..."

# redis-cli -u handles full URL parsing (TLS, auth, host, port, db)
# --no-auth-warning suppresses the "Using a password with the -a option..."
# warning that appears with older redis-cli versions when auth is embedded in URL
if ! redis-cli -u "$REDIS_URL" --no-auth-warning PING > /dev/null 2>&1; then
    echo "[check_redis_aof] ERROR: Cannot connect to Redis at ${SAFE_URL}" >&2
    exit 2
fi

APPENDONLY_VALUE=$(redis-cli -u "$REDIS_URL" --no-auth-warning CONFIG GET appendonly 2>/dev/null | tail -1 | tr -d '[:space:]')

echo "[check_redis_aof] appendonly = '${APPENDONLY_VALUE}'"

if [ "$APPENDONLY_VALUE" = "yes" ]; then
    echo "[check_redis_aof] PASS — AOF persistence is enabled."
    exit 0
else
    cat >&2 <<'EOF'
[check_redis_aof] FAIL — Redis appendonly is not enabled.

Distributed job locks require AOF persistence to survive Redis restarts.
Without it, a pod restart can cause two pods to hold the same lock
simultaneously (split-brain), leading to duplicate job execution.

To fix:
  1. Enable AOF at runtime (takes effect immediately):
       redis-cli -u "$REDIS_URL" CONFIG SET appendonly yes
       redis-cli -u "$REDIS_URL" BGREWRITEAOF

  2. Make it permanent in redis.conf:
       appendonly yes

  3. Re-run this check to confirm:
       ./scripts/check_redis_aof.sh

See: https://redis.io/docs/management/persistence/#aof-advantages
EOF
    exit 1
fi
