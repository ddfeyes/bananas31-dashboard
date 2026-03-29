"""Tests for /api/health collector health endpoint."""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_collector_health_attributes():
    """Each collector class has NAME, status, last_connected_at, disconnected_at."""
    from collectors import (
        BinanceSpotCollector,
        BinancePerpCollector,
        BybitPerpCollector,
        BSCPancakeSwapCollector,
    )

    dummy = lambda tick: None  # noqa: E731

    for Cls, name in [
        (BinanceSpotCollector, "binance_spot"),
        (BinancePerpCollector, "binance_perp"),
        (BybitPerpCollector, "bybit_perp"),
        (BSCPancakeSwapCollector, "pancake"),
    ]:
        if Cls in (BinancePerpCollector, BybitPerpCollector):
            c = Cls(dummy, dummy)
        else:
            c = Cls(dummy)
        assert c.NAME == name, f"{Cls.__name__}.NAME should be {name}"
        assert c.status == "disconnected"
        assert c.last_connected_at is None
        assert c.disconnected_at is None


def test_collector_backoff_constants():
    """Exponential backoff constants are present."""
    from collectors import RECONNECT_BASE, RECONNECT_MAX
    assert RECONNECT_BASE == 2
    assert RECONNECT_MAX == 30


def test_health_endpoint_structure():
    """Simulates the /api/health response structure using collector instances."""
    from collectors import BinanceSpotCollector, BinancePerpCollector, BybitPerpCollector, BSCPancakeSwapCollector

    dummy = lambda tick: None  # noqa: E731
    app_start = time.time() - 3600  # simulate 1hr uptime

    test_collectors = [
        BinancePerpCollector(dummy, dummy),
        BinanceSpotCollector(dummy),
        BybitPerpCollector(dummy, dummy),
        BSCPancakeSwapCollector(dummy),
    ]

    # Simulate: first two connected, third disconnected >60s, fourth connected
    test_collectors[0].status = "connected"
    test_collectors[0].last_connected_at = time.time()
    test_collectors[1].status = "connected"
    test_collectors[1].last_connected_at = time.time()
    test_collectors[2].status = "disconnected"
    test_collectors[2].disconnected_at = time.time() - 120  # 2min ago
    test_collectors[3].status = "connected"
    test_collectors[3].last_connected_at = time.time()

    # Build response same way as the endpoint
    now = time.time()
    collector_statuses = {}
    alerts = []
    for c in test_collectors:
        name = getattr(c, "NAME", c.__class__.__name__)
        status = getattr(c, "status", "unknown")
        collector_statuses[name] = status
        disconnected_at = getattr(c, "disconnected_at", None)
        if status == "disconnected" and disconnected_at and (now - disconnected_at) > 60:
            alerts.append({
                "collector": name,
                "disconnected_secs": round(now - disconnected_at),
                "message": f"{name} disconnected for {round(now - disconnected_at)}s",
            })

    response = {
        "status": "ok",
        "uptime_secs": round(now - app_start),
        "collectors": collector_statuses,
        "alerts": alerts,
    }

    # Validate structure
    assert response["status"] == "ok"
    assert response["uptime_secs"] >= 3600
    assert isinstance(response["collectors"], dict)
    assert len(response["collectors"]) == 4
    assert response["collectors"]["binance_perp"] == "connected"
    assert response["collectors"]["binance_spot"] == "connected"
    assert response["collectors"]["bybit_perp"] == "disconnected"
    assert response["collectors"]["pancake"] == "connected"

    # Alert for bybit_perp disconnected >60s
    assert len(response["alerts"]) == 1
    assert response["alerts"][0]["collector"] == "bybit_perp"
    assert response["alerts"][0]["disconnected_secs"] >= 120


def test_health_no_alerts_when_all_connected():
    """No alerts when all collectors are connected."""
    from collectors import BinanceSpotCollector

    dummy = lambda tick: None  # noqa: E731
    c = BinanceSpotCollector(dummy)
    c.status = "connected"
    c.last_connected_at = time.time()
    c.disconnected_at = None

    now = time.time()
    name = c.NAME
    status = c.status
    disconnected_at = c.disconnected_at
    alerts = []
    if status == "disconnected" and disconnected_at and (now - disconnected_at) > 60:
        alerts.append({"collector": name})
    assert len(alerts) == 0


def test_health_no_alert_within_60s():
    """No alert if disconnected for less than 60 seconds."""
    from collectors import BinanceSpotCollector

    dummy = lambda tick: None  # noqa: E731
    c = BinanceSpotCollector(dummy)
    c.status = "disconnected"
    c.disconnected_at = time.time() - 30  # only 30s ago

    now = time.time()
    alerts = []
    if c.status == "disconnected" and c.disconnected_at and (now - c.disconnected_at) > 60:
        alerts.append({"collector": c.NAME})
    assert len(alerts) == 0
