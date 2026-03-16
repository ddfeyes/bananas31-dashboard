"""
Tests for the RV vs IV (Realized Volatility vs Implied Volatility) card (wave 12).
Covers:
  - HTML card presence
  - JS render function presence
  - Python mirrors of display logic (ratio calculation, badge state)
"""
import os
import pytest

_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _html() -> str:
    with open(os.path.join(_ROOT, "frontend", "index.html"), encoding="utf-8") as f:
        return f.read()


def _js() -> str:
    with open(os.path.join(_ROOT, "frontend", "app.js"), encoding="utf-8") as f:
        return f.read()


# ── Python mirrors of renderRvIv logic ────────────────────────────────────────

def rv_iv_ratio_state(ratio: float | None) -> str:
    if ratio is None:
        return "unknown"
    if ratio < 0.85:
        return "compressed"
    if ratio < 1.0:
        return "normal"
    return "elevated"


def rv_iv_badge_class(state: str) -> str:
    mapping = {
        "compressed": "badge-blue",
        "normal": "badge-green",
        "elevated": "badge-red",
    }
    return mapping.get(state, "badge-yellow")


def compute_iv_from_rv(rv: float, funding_rate: float | None) -> float:
    """Mirrors app.js IV estimation logic."""
    if funding_rate is not None:
        abs_f = abs(funding_rate)
        return rv * (1 + abs_f * 50)
    return rv * 1.15


# ── HTML tests ────────────────────────────────────────────────────────────────

class TestRvIvHtml:
    def test_card_section_present(self):
        html = _html()
        assert 'id="card-rv-iv"' in html

    def test_card_title_present(self):
        html = _html()
        assert "RV vs IV" in html

    def test_badge_element_present(self):
        html = _html()
        assert 'id="rv-iv-badge"' in html

    def test_content_element_present(self):
        html = _html()
        assert 'id="rv-iv-content"' in html

    def test_card_meta_present(self):
        html = _html()
        assert "realized vs implied vol" in html or "realized vol" in html


# ── JS tests ─────────────────────────────────────────────────────────────────

class TestRvIvJs:
    def test_render_function_present(self):
        js = _js()
        assert "renderRvIv" in js

    def test_render_function_in_refresh(self):
        js = _js()
        assert "safe(renderRvIv)" in js

    def test_rv_iv_content_id_referenced(self):
        js = _js()
        assert "rv-iv-content" in js

    def test_rv_iv_badge_id_referenced(self):
        js = _js()
        assert "rv-iv-badge" in js

    def test_realized_vol_endpoint_used(self):
        js = _js()
        assert "realized-volatility-bands" in js


# ── Logic tests ──────────────────────────────────────────────────────────────

class TestRvIvLogic:
    def test_ratio_compressed(self):
        rv, iv = 0.01, 0.02  # RV much less than IV
        ratio = rv / iv  # 0.5
        assert rv_iv_ratio_state(ratio) == "compressed"
        assert rv_iv_badge_class("compressed") == "badge-blue"

    def test_ratio_normal(self):
        rv, iv = 0.009, 0.01  # RV slightly below IV
        ratio = rv / iv  # 0.9
        assert rv_iv_ratio_state(ratio) == "normal"
        assert rv_iv_badge_class("normal") == "badge-green"

    def test_ratio_elevated(self):
        rv, iv = 0.015, 0.01  # RV above IV
        ratio = rv / iv  # 1.5
        assert rv_iv_ratio_state(ratio) == "elevated"
        assert rv_iv_badge_class("elevated") == "badge-red"

    def test_ratio_none_unknown(self):
        assert rv_iv_ratio_state(None) == "unknown"
        assert rv_iv_badge_class("unknown") == "badge-yellow"

    def test_iv_from_rv_no_funding(self):
        rv = 0.01
        iv = compute_iv_from_rv(rv, None)
        assert abs(iv - rv * 1.15) < 1e-10

    def test_iv_from_rv_with_funding(self):
        rv = 0.01
        funding = 0.0001  # 0.01% funding
        iv = compute_iv_from_rv(rv, funding)
        expected = rv * (1 + abs(funding) * 50)
        assert abs(iv - expected) < 1e-10

    def test_iv_from_rv_high_funding(self):
        rv = 0.01
        funding = 0.002  # 0.2% funding (stressed market)
        iv = compute_iv_from_rv(rv, funding)
        # With 0.2% funding: rv * (1 + 0.002 * 50) = rv * 1.1 → IV > RV
        assert iv > rv

    @pytest.mark.parametrize("ratio,expected_state", [
        (0.5, "compressed"),
        (0.84, "compressed"),
        (0.85, "normal"),
        (0.99, "normal"),
        (1.0, "elevated"),
        (1.5, "elevated"),
        (2.0, "elevated"),
    ])
    def test_ratio_boundaries(self, ratio, expected_state):
        assert rv_iv_ratio_state(ratio) == expected_state
