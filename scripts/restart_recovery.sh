#!/usr/bin/env bash
# restart_recovery.sh — Run the svc-dash restart-recovery integration test suite.
#
# Usage:
#   ./scripts/restart_recovery.sh           # run with default verbosity
#   ./scripts/restart_recovery.sh -v        # verbose output
#   ./scripts/restart_recovery.sh --help    # show pytest help
#
# Requires:
#   - Docker and docker compose accessible on the host
#   - svc-dash service running at localhost:8765 before invocation
#   - Python packages: pytest, requests (pip install pytest requests)
#
# The test suite:
#   1. Verifies the service is healthy before restart
#   2. Executes `docker compose restart`
#   3. Waits up to 90 s for the service to come back
#   4. Spot-checks all key endpoints for valid structure and data continuity

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> svc-dash restart recovery test"
echo "    repo: ${REPO_ROOT}"
echo "    date: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo ""

cd "${REPO_ROOT}"

exec pytest tests/test_restart_recovery.py \
    -m "slow and integration" \
    -v \
    --tb=short \
    "$@"
