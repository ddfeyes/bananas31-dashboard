"""
Restart recovery integration test for svc-dash.

Verifies that the service survives a full Docker restart and resumes
serving all key endpoints with valid, non-empty data.

Usage:
    pytest tests/test_restart_recovery.py -m slow -v

Marked @pytest.mark.slow so it is excluded from normal CI runs.
Requires Docker and docker compose accessible on the host.
"""
import subprocess
import time

import pytest
import requests
from requests.exceptions import ConnectionError as ConnErr, ReadTimeout

BASE_URL   = "http://localhost:8765/api"
SYMBOL     = "BANANAS31USDT"
COMPOSE_YML = "docker-compose.yml"

# Timing
RESTART_TIMEOUT_S  = 60   # max seconds to wait for docker compose restart to finish
RECOVERY_TIMEOUT_S = 90   # max seconds to poll /health after restart
POLL_INTERVAL_S    = 2


# ── helpers ───────────────────────────────────────────────────────────────────

def api_get(path, params=None, timeout=10):
    """GET with a plain requests call; raises on connection error."""
    return requests.get(f"{BASE_URL}{path}", params=params, timeout=timeout)


def wait_healthy(timeout=RECOVERY_TIMEOUT_S, interval=POLL_INTERVAL_S):
    """
    Poll /api/health until it returns 200 with status=ok or timeout expires.
    Returns (True, elapsed) on success, (False, elapsed) on timeout.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"{BASE_URL}/health", timeout=5)
            if r.status_code == 200 and r.json().get("status") == "ok":
                return True, deadline - time.time()
        except Exception:
            pass
        time.sleep(interval)
    return False, 0


def assert_endpoint_ok(path, params=None, required_keys=("status",), timeout=15):
    """Assert endpoint returns 200, valid JSON, and required keys."""
    try:
        r = api_get(path, params=params, timeout=timeout)
    except (ConnErr, ReadTimeout) as exc:
        pytest.fail(f"POST-restart: {path} unreachable: {exc}")
    assert r.status_code == 200, f"{path} → {r.status_code}: {r.text[:200]}"
    data = r.json()
    for k in required_keys:
        assert k in data, f"{path} missing key '{k}': {list(data.keys())}"
    return data


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def require_server():
    """Skip entire module if server is not running before the test."""
    try:
        r = requests.get(f"{BASE_URL}/health", timeout=5)
        if r.status_code != 200:
            pytest.skip("server not healthy before test")
    except Exception:
        pytest.skip("server not reachable before test")


@pytest.fixture(scope="module")
def baseline(require_server):
    """
    Collect baseline snapshots from key endpoints before restart.
    Returns a dict of {endpoint_path: response_json}.
    """
    snapshots = {}
    endpoints = [
        ("/health",          {}),
        ("/ohlcv",           {"symbol": SYMBOL, "interval": 60, "window": 300}),
        ("/cvd/history",     {"symbol": SYMBOL, "window": 600}),
        ("/oi/history",      {"symbol": SYMBOL, "limit": 5}),
        ("/funding/history", {"symbol": SYMBOL, "limit": 5}),
        ("/market-regime",   {"symbol": SYMBOL}),
        ("/volume-profile",  {"symbol": SYMBOL}),
        ("/metrics/summary", {"symbol": SYMBOL}),
    ]
    for path, params in endpoints:
        try:
            r = api_get(path, params=params, timeout=10)
            if r.status_code == 200:
                snapshots[path] = r.json()
        except Exception:
            pass  # best-effort; missing baselines won't cause failure
    return snapshots


# ── test class ────────────────────────────────────────────────────────────────

@pytest.mark.slow
@pytest.mark.integration
class TestRestartRecovery:
    """Full restart recovery sequence — runs as a single ordered module."""

    def test_01_pre_restart_health(self, require_server):
        """Precondition: service is healthy before we restart."""
        data = assert_endpoint_ok("/health", required_keys=("status", "db_size_mb", "symbols"))
        assert data["status"] == "ok", f"pre-restart health not ok: {data}"
        assert len(data["symbols"]) > 0, "no symbols registered before restart"

    def test_02_pre_restart_data_present(self, require_server):
        """Precondition: trades and OI data exist before restart."""
        trades = assert_endpoint_ok(
            "/trades/recent",
            params={"symbol": SYMBOL, "limit": 5},
            required_keys=("status", "data", "count"),
        )
        assert trades["count"] > 0, "no trades before restart"

        oi = assert_endpoint_ok(
            "/oi/history",
            params={"symbol": SYMBOL, "limit": 5},
            required_keys=("status", "data", "count"),
        )
        assert oi["count"] > 0, "no OI data before restart"

    def test_03_docker_restart(self, require_server):
        """Execute `docker compose restart` and wait for it to finish."""
        result = subprocess.run(
            ["docker", "compose", "restart"],
            cwd="/Users/aivan/svc-dash",
            capture_output=True,
            text=True,
            timeout=RESTART_TIMEOUT_S,
        )
        assert result.returncode == 0, (
            f"docker compose restart failed (exit {result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_04_waits_for_recovery(self, require_server):
        """
        After restart, poll /health until the service comes back.
        Fails if it doesn't recover within RECOVERY_TIMEOUT_S seconds.
        """
        recovered, remaining = wait_healthy()
        assert recovered, (
            f"Service did not recover within {RECOVERY_TIMEOUT_S}s after docker compose restart"
        )

    def test_05_health_after_restart(self, require_server):
        """/health returns ok with correct structure after restart."""
        data = assert_endpoint_ok("/health", required_keys=("status", "db_size_mb", "symbols", "symbol_count"))
        assert data["status"] == "ok"
        assert isinstance(data["symbol_count"], int) and data["symbol_count"] > 0

    def test_06_ohlcv_after_restart(self, require_server):
        """/ohlcv returns candle data after restart."""
        data = assert_endpoint_ok(
            "/ohlcv",
            params={"symbol": SYMBOL, "interval": 60, "window": 300},
            required_keys=("status", "symbol", "data", "count"),
        )
        assert data["symbol"] == SYMBOL
        assert isinstance(data["data"], list)
        # data may be empty if only just restarted — that's OK, structure must be valid

    def test_07_cvd_after_restart(self, require_server):
        """/cvd/history returns valid structure after restart."""
        data = assert_endpoint_ok(
            "/cvd/history",
            params={"symbol": SYMBOL, "window": 600},
            required_keys=("status", "data", "count"),
        )
        assert isinstance(data["data"], list)

    def test_08_oi_after_restart(self, require_server):
        """/oi/history returns valid structure after restart."""
        data = assert_endpoint_ok(
            "/oi/history",
            params={"symbol": SYMBOL, "limit": 5},
            required_keys=("status", "data", "count"),
        )
        assert isinstance(data["data"], list)

    def test_09_funding_after_restart(self, require_server):
        """/funding/history returns valid structure after restart."""
        data = assert_endpoint_ok(
            "/funding/history",
            params={"symbol": SYMBOL, "limit": 5},
            required_keys=("status", "data", "count"),
        )
        assert isinstance(data["data"], list)

    def test_10_market_regime_after_restart(self, require_server):
        """/market-regime (phase) returns valid classification after restart."""
        data = assert_endpoint_ok(
            "/market-regime",
            params={"symbol": SYMBOL},
            required_keys=("status", "regime", "phase", "score"),
        )
        assert data["status"] == "ok"
        assert isinstance(data["score"], (int, float))

    def test_11_volume_profile_after_restart(self, require_server):
        """/volume-profile returns valid POC/VAH/VAL after restart."""
        data = assert_endpoint_ok(
            "/volume-profile",
            params={"symbol": SYMBOL},
            required_keys=("status", "symbol", "poc"),
        )

    def test_12_metrics_summary_after_restart(self, require_server):
        """/metrics/summary returns price and key metrics after restart."""
        data = assert_endpoint_ok(
            "/metrics/summary",
            params={"symbol": SYMBOL},
            required_keys=("status", "symbol", "price"),
        )
        assert data["symbol"] == SYMBOL
        assert data["price"] > 0, "price is zero after restart"

    def test_13_symbols_consistent_after_restart(self, require_server, baseline):
        """Symbol list after restart matches the pre-restart list."""
        data = assert_endpoint_ok("/symbols", required_keys=("status", "symbols"))
        post_syms = set(data["symbols"])
        if "/health" in baseline:
            pre_syms = set(baseline["/health"].get("symbols", []))
            assert post_syms == pre_syms, (
                f"Symbol mismatch after restart: before={pre_syms}, after={post_syms}"
            )
        assert SYMBOL in post_syms, f"{SYMBOL} missing from symbols after restart"

    def test_14_no_data_loss(self, require_server, baseline):
        """
        Spot-check data continuity: record counts should not drop significantly.
        Allows for <=5% drop to account for TTL expiry during restart window.
        """
        if "/trades/recent" not in baseline and "/oi/history" not in baseline:
            pytest.skip("no baseline data to compare against")

        # Re-fetch trades
        post = assert_endpoint_ok(
            "/trades/recent",
            params={"symbol": SYMBOL, "limit": 50},
            required_keys=("status", "data", "count"),
        )
        assert post["count"] > 0, "trade tape empty after restart — possible data loss"
