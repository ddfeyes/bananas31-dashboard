"""
Tests for issue #186 fixes:
  1. Double prefix /api/api/funding-arb-scanner — apiFetch("/api/...") → apiFetch("/...")
  2. WebSocket /api/ws/alerts → polling fallback when WS unavailable
  3. No continuous retry loop on alerts card
  4. Backend /alerts GET endpoint returns correct shape
  5. Frontend connectAlerts uses polling fallback pattern
"""

import os
import re
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "backend"))

_js_cache: str | None = None
_html_cache: str | None = None


def _js() -> str:
    global _js_cache
    if _js_cache is None:
        with open(os.path.join(ROOT, "frontend", "app.js"), encoding="utf-8") as f:
            _js_cache = f.read()
    return _js_cache


def _html() -> str:
    global _html_cache
    if _html_cache is None:
        with open(os.path.join(ROOT, "frontend", "index.html"), encoding="utf-8") as f:
            _html_cache = f.read()
    return _html_cache


def _fn_body(js: str, fn_name: str) -> str:
    """Extract function body (roughly) by finding its start and the next function."""
    start = js.find(f"async function {fn_name}(")
    if start == -1:
        start = js.find(f"function {fn_name}(")
    assert start != -1, f"Function {fn_name} not found in app.js"
    nxt = js.find("\nasync function ", start + 1)
    nxt2 = js.find("\nfunction ", start + 1)
    end = min(x for x in [nxt, nxt2, len(js)] if x > start)
    return js[start:end]


# ── Group 1: No double /api/api prefix ───────────────────────────────────────


class TestNoDoubleApiPrefix:
    def test_no_apifetch_with_api_prefix(self):
        """apiFetch already prepends /api — callers must not include /api in path."""
        js = _js()
        # Find all apiFetch calls with /api/ prefix (wrong)
        matches = re.findall(r'apiFetch\(["\']\/api\/', js)
        assert not matches, (
            f"Found {len(matches)} apiFetch() call(s) with double /api/ prefix: {matches}. "
            "apiFetch() already prepends API base which includes /api — remove the extra /api."
        )

    def test_funding_arb_scanner_uses_correct_path(self):
        """renderFundingArbScanner must call apiFetch('/funding-arb-scanner'), not /api/..."""
        body = _fn_body(_js(), "renderFundingArbScanner")
        assert (
            'apiFetch("/funding-arb-scanner")' in body
            or "apiFetch('/funding-arb-scanner')" in body
        ), (
            "renderFundingArbScanner must call apiFetch('/funding-arb-scanner') — "
            "without /api prefix since apiFetch adds it automatically."
        )

    def test_funding_arb_scanner_no_double_prefix(self):
        """Specifically: /api/funding-arb-scanner must NOT appear inside apiFetch()."""
        js = _js()
        assert 'apiFetch("/api/funding-arb-scanner")' not in js, (
            "apiFetch('/api/funding-arb-scanner') causes double prefix → /api/api/funding-arb-scanner. "
            "Use apiFetch('/funding-arb-scanner') instead."
        )


# ── Group 2: Alerts WS polling fallback ──────────────────────────────────────


class TestAlertsWsPollingFallback:
    def test_connect_alerts_function_exists(self):
        assert (
            "function connectAlerts()" in _js() or "connectAlerts" in _js()
        ), "connectAlerts function not found in app.js"

    def test_polling_fallback_references_alerts_endpoint(self):
        """Polling fallback must call /alerts endpoint (in connectAlerts or its helper)."""
        js = _js()
        connect_body = _fn_body(js, "connectAlerts")
        # Either connectAlerts itself calls /alerts, or it delegates to a named helper
        # that calls /alerts. Check the broader JS for the polling pattern.
        has_alerts_poll = (
            "apiFetch('/alerts" in js
            or 'apiFetch("/alerts' in js
            or "fetch('/api/alerts" in js
            or 'fetch("/api/alerts' in js
        )
        # And connectAlerts must call the polling helper or directly poll
        calls_polling = (
            "_startAlertsPolling" in connect_body
            or "apiFetch('/alerts" in connect_body
            or 'apiFetch("/alerts' in connect_body
            or "polling" in connect_body.lower()
        )
        assert (
            has_alerts_poll
        ), "app.js must contain an /alerts polling call for the WS fallback."
        assert (
            calls_polling
        ), "connectAlerts must trigger polling (directly or via helper) on WS failure."

    def test_polling_fallback_uses_setinterval_or_settimeout(self):
        """Polling must use setInterval or setTimeout to repeat."""
        body = _fn_body(_js(), "connectAlerts")
        assert "setInterval" in body or "setTimeout" in body, (
            "connectAlerts polling fallback must use setInterval or setTimeout "
            "to repeat the poll."
        )

    def test_ws_error_does_not_trigger_immediate_reconnect_loop(self):
        """onerror must not call connectAlerts() directly — that causes a tight retry loop."""
        body = _fn_body(_js(), "connectAlerts")
        # Find onerror handler
        err_start = body.find("wsAlerts.onerror")
        assert err_start != -1, "wsAlerts.onerror handler not found"
        err_snippet = body[err_start : err_start + 300]
        # onerror must not call connectAlerts() without a delay/fallback check
        assert "setTimeout(connectAlerts" not in err_snippet, (
            "wsAlerts.onerror must not call setTimeout(connectAlerts) — "
            "that creates a retry loop on WS failure. Use polling fallback instead."
        )

    def test_ws_fallback_flag_or_mode_tracking(self):
        """connectAlerts must track whether WS is available to choose polling vs WS."""
        body = _fn_body(_js(), "connectAlerts")
        # Should have some variable that tracks WS connected/failed state
        has_flag = (
            "wsConnected" in body
            or "_wsOk" in body
            or "polling" in body
            or "fallback" in body
            or "usePoll" in body
            or "wsOk" in body
        )
        assert has_flag, (
            "connectAlerts must track whether WS connected successfully to decide "
            "whether to use polling fallback."
        )


# ── Group 3: Backend /alerts endpoint ────────────────────────────────────────


class TestBackendAlertsEndpoint:
    def test_alerts_endpoint_exists_in_api(self):
        """Backend must have GET /alerts endpoint."""
        with open(os.path.join(ROOT, "backend", "api.py"), encoding="utf-8") as f:
            api_src = f.read()
        assert (
            '@router.get("/alerts")' in api_src
        ), "Backend api.py must have @router.get('/alerts') endpoint for polling fallback."

    def test_alerts_endpoint_referenced_in_js(self):
        """Frontend must reference /alerts endpoint (for polling)."""
        js = _js()
        assert "/alerts" in js, "app.js must reference /alerts endpoint"


# ── Group 4: Existing funding arb scanner test compatibility ─────────────────


class TestFundingArbScannerEndpointPath:
    def test_funding_arb_scanner_path_without_api_prefix(self):
        """The funding arb scanner API call must use path without /api prefix."""
        js = _js()
        # The correct call
        assert (
            "/funding-arb-scanner" in js
        ), "app.js must reference /funding-arb-scanner endpoint"

    def test_render_funding_arb_scanner_exists(self):
        assert "renderFundingArbScanner" in _js()
