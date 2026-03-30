"""
Validate that the execution bot's v3.0 logic matches the backtest engine.
Tests entry gates, sizing, grid construction, and timeout independently.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Mock environment variables BEFORE importing config (which reads them at import time)
os.environ.setdefault("HL_PRIVATE_KEY", "0x0000000000000000000000000000000000000000000000000000000000000001")
os.environ.setdefault("HL_MAIN_ADDRESS", "0x0000000000000000000000000000000000000000")

import pytest
from execution import config as cfg
from execution.grid_state import build_levels, LONG, SHORT


class TestConfig:
    def test_version(self):
        assert cfg.BOT_VERSION == "3.0.0"

    def test_risk_params(self):
        assert cfg.RISK_PCT == 0.50
        assert cfg.RESCUE_RISK_PCT == 0.28
        assert cfg.LEVEL_MULTS_SEQ == [2.0, 2.5, 2.5, 7.0]

    def test_gaps(self):
        assert cfg.LEVEL_GAPS == [0.5, 1.5, 10.0, 14.0]
        assert cfg.CUM_DROPS == pytest.approx([0.005, 0.02, 0.12, 0.26])

    def test_triggers(self):
        assert cfg.LONG_TRIGGER_PCT == 0.5
        assert cfg.EMA20_TRIGGER_PCT == 2.0
        assert cfg.SHORT_TRIGGER_PCT == 8.0

    def test_regime_scaling(self):
        assert cfg.UNFAV_RISK_SCALE == 0.60
        assert cfg.UNFAV_SPACING_SCALE == 1.60
        assert cfg.UNFAV_TRIGGER_SCALE == 3.0
        assert cfg.UNFAV_HOLD_SCALE == 0.45

    def test_timeout_bars(self):
        assert cfg.MAX_HOLD_BARS == 720
        assert int(cfg.MAX_HOLD_BARS * cfg.UNFAV_HOLD_SCALE) == 324


class TestBuildLevels:
    def test_favored_long_sizing(self):
        """v3.0 sizing: L1=1x, L2=2x, L3=5x, L4=12.5x, L5=87.5x of L1 notional"""
        levels = build_levels(50000, LONG, risk_pct=0.50, balance=400.0, is_favored=True)
        assert len(levels) == 5
        l1_n = 0.50 * 400.0
        assert levels[0].notional == pytest.approx(l1_n)
        assert levels[1].notional == pytest.approx(l1_n * 2.0)
        assert levels[2].notional == pytest.approx(l1_n * 5.0)
        assert levels[3].notional == pytest.approx(l1_n * 12.5)
        assert levels[4].notional == pytest.approx(l1_n * 87.5)

    def test_favored_long_prices(self):
        """Grid prices: L1=trigger, L2=-0.5%, L3=-2%, L4=-12%, L5=-26%"""
        levels = build_levels(100000, LONG, risk_pct=0.50, balance=1000.0, is_favored=True)
        assert levels[0].target_px == pytest.approx(100000, rel=0.001)
        assert levels[1].target_px == pytest.approx(100000 * 0.995, rel=0.001)
        assert levels[2].target_px == pytest.approx(100000 * 0.98, rel=0.001)
        assert levels[3].target_px == pytest.approx(100000 * 0.88, rel=0.001)
        assert levels[4].target_px == pytest.approx(100000 * 0.74, rel=0.001)

    def test_unfavored_long_spacing(self):
        """Unfavored gaps: x1.6 -> [0.8, 2.4, 16.0, 22.4]%"""
        levels = build_levels(100000, LONG, risk_pct=0.30, balance=1000.0, is_favored=False)
        assert levels[1].target_px == pytest.approx(100000 * (1 - 0.008), rel=0.001)
        assert levels[2].target_px == pytest.approx(100000 * (1 - 0.032), rel=0.001)
        assert levels[3].target_px == pytest.approx(100000 * (1 - 0.192), rel=0.001)
        assert levels[4].target_px == pytest.approx(100000 * (1 - 0.416), rel=0.001)

    def test_unfavored_risk_sizing(self):
        """Unfavored L1 notional = 0.30 x balance"""
        levels = build_levels(50000, LONG, risk_pct=0.30, balance=400.0, is_favored=False)
        assert levels[0].notional == pytest.approx(0.30 * 400.0)

    def test_rescue_risk_sizing(self):
        """Rescue L1 notional = 0.28 x balance (favored) or 0.168 (unfavored)"""
        levels_f = build_levels(50000, LONG, risk_pct=0.28, balance=1000.0, is_favored=True)
        assert levels_f[0].notional == pytest.approx(280.0)
        levels_u = build_levels(50000, LONG, risk_pct=0.168, balance=1000.0, is_favored=False)
        assert levels_u[0].notional == pytest.approx(168.0)

    def test_short_levels_ladder_up(self):
        """SHORT levels ladder UP from trigger"""
        levels = build_levels(50000, SHORT, risk_pct=0.50, balance=400.0, is_favored=True)
        for i in range(1, len(levels)):
            assert levels[i].target_px > levels[i - 1].target_px

    def test_margin_is_notional_over_leverage(self):
        levels = build_levels(50000, LONG, risk_pct=0.50, balance=400.0, is_favored=True)
        for lv in levels:
            assert lv.margin == pytest.approx(lv.notional / cfg.LEVERAGE)


class TestEntryLogic:
    """Test long_triggered / short_triggered with mock market state dicts.

    We extract the pure trigger functions from grid_bot.py source code and
    exec them in an isolated namespace to avoid importing hl_client (which
    requires the Hyperliquid SDK).
    """

    @pytest.fixture(autouse=True)
    def _patch_paper_mode(self, monkeypatch):
        """Placeholder — actual import bypass is in _get_trigger_funcs."""
        pass

    def _make_state(self, price=50000, ema34=50500, sma14=50400, ema20=50300,
                    sma440=48000, high_20d=52000, rsi14=45.0, is_bull=True):
        return {
            "price": price,
            "ema34": ema34,
            "sma14": sma14,
            "ema20": ema20,
            "sma440": sma440,
            "high_20d": high_20d,
            "rsi14": rsi14,
            "is_bull": is_bull,
        }

    def _get_trigger_funcs(self):
        """Import the pure trigger functions without triggering hl_client import.
        We extract pct_above, pct_below, long_triggered, short_triggered by
        parsing the source and exec'ing just the relevant functions."""
        import types
        import pathlib
        import re

        # Read grid_bot source
        src = pathlib.Path(os.path.join(os.path.dirname(__file__), "..", "grid_bot.py")).read_text(encoding="utf-8")

        # Create a minimal module with just the functions we need
        mod = types.ModuleType("grid_bot_logic")
        mod.cfg = cfg

        # Extract and exec the helper functions
        funcs_code = []
        for fname in ["pct_above", "pct_below", "long_triggered", "short_triggered"]:
            pattern = rf"(def {fname}\(.*?\n(?:(?!^def ).*\n)*)"
            match = re.search(pattern, src, re.MULTILINE)
            if match:
                funcs_code.append(match.group(1))

        code = "\n".join(funcs_code)
        exec(compile(code, "grid_bot_logic", "exec"), mod.__dict__)
        return mod

    def test_no_sma440_blocks_entry(self):
        mod = self._get_trigger_funcs()
        state = self._make_state(is_bull=None)
        t, gate, risk = mod.long_triggered(state)
        assert not t
        assert gate == "no_sma440"

    def test_v28_gate_fires(self):
        mod = self._get_trigger_funcs()
        state = self._make_state(price=50000, ema34=50500, sma14=50400, is_bull=True)
        t, gate, risk = mod.long_triggered(state)
        assert t
        assert gate == "v28"
        assert risk == pytest.approx(0.50)

    def test_ema20_gate_fires(self):
        mod = self._get_trigger_funcs()
        state = self._make_state(price=50000, ema34=50100, sma14=50100, ema20=51300, is_bull=True)
        t, gate, risk = mod.long_triggered(state)
        assert t
        assert gate == "ema20"

    def test_unfavored_trigger_scaling(self):
        mod = self._get_trigger_funcs()
        # Not enough below for unfavored (needs 1.5%)
        state = self._make_state(price=50000, ema34=50300, sma14=50300, ema20=50300, is_bull=False)
        t, gate, risk = mod.long_triggered(state)
        assert not t

        # Enough below for unfavored
        state2 = self._make_state(price=49000, ema34=50000, sma14=50000, ema20=51000, is_bull=False)
        t2, gate2, risk2 = mod.long_triggered(state2)
        assert t2
        assert risk2 == pytest.approx(0.50 * 0.60)

    def test_dd20d_blocks_entry(self):
        mod = self._get_trigger_funcs()
        state = self._make_state(price=49000, ema34=50000, sma14=50000,
                                 high_20d=55000, rsi14=45.0, is_bull=True)
        t, gate, risk = mod.long_triggered(state)
        assert not t
        assert gate == "dd20d_blocked"

    def test_rsi_rescue(self):
        mod = self._get_trigger_funcs()
        state = self._make_state(price=49000, ema34=50000, sma14=50000,
                                 high_20d=55000, rsi14=28.0, is_bull=True)
        t, gate, risk = mod.long_triggered(state)
        assert t
        assert gate == "rescued"
        assert risk == pytest.approx(0.28)

    def test_rsi_rescue_unfavored(self):
        mod = self._get_trigger_funcs()
        state = self._make_state(price=49000, ema34=50000, sma14=50000,
                                 high_20d=55000, rsi14=25.0, is_bull=False)
        t, gate, risk = mod.long_triggered(state)
        assert t
        assert gate == "rescued"
        assert risk == pytest.approx(0.28 * 0.60)

    def test_short_trigger_favored(self):
        mod = self._get_trigger_funcs()
        state = self._make_state(price=54500, ema34=50000, sma14=50000, is_bull=False)
        t, gate, risk = mod.short_triggered(state)
        assert t
        assert risk == pytest.approx(0.50)

    def test_short_trigger_unfavored(self):
        mod = self._get_trigger_funcs()
        state = self._make_state(price=55000, ema34=50000, sma14=50000, is_bull=True)
        t, gate, risk = mod.short_triggered(state)
        assert not t

    def test_no_trigger_idle(self):
        mod = self._get_trigger_funcs()
        state = self._make_state(price=50000, ema34=50050, sma14=50050, ema20=50050, is_bull=True)
        tl, _, _ = mod.long_triggered(state)
        ts, _, _ = mod.short_triggered(state)
        assert not tl
        assert not ts


class TestTimeout:
    def test_favored_timeout_hours(self):
        assert cfg.MAX_HOLD_BARS * 4 == 2880

    def test_unfavored_timeout_hours(self):
        bars = int(cfg.MAX_HOLD_BARS * cfg.UNFAV_HOLD_SCALE)
        assert bars == 324
        assert bars * 4 == 1296


class TestBacktestAlignment:
    def test_cum_mults_match_spec(self):
        mults = [1.0]
        for m in cfg.LEVEL_MULTS_SEQ:
            mults.append(mults[-1] * m)
        assert mults == pytest.approx([1.0, 2.0, 5.0, 12.5, 87.5])

    def test_favored_cum_drops_match_spec(self):
        assert cfg.CUM_DROPS == pytest.approx([0.005, 0.02, 0.12, 0.26])

    def test_unfavored_cum_drops_match_spec(self):
        scale = cfg.UNFAV_SPACING_SCALE
        unfav_drops = []
        acc = 0.0
        for g in cfg.LEVEL_GAPS:
            acc += g * scale
            unfav_drops.append(acc / 100.0)
        assert unfav_drops == pytest.approx([0.008, 0.032, 0.192, 0.416])

    def test_risk_combinations(self):
        favored_normal = cfg.RISK_PCT
        unfavored_normal = cfg.RISK_PCT * cfg.UNFAV_RISK_SCALE
        favored_rescued = cfg.RESCUE_RISK_PCT
        unfavored_rescued = cfg.RESCUE_RISK_PCT * cfg.UNFAV_RISK_SCALE
        assert favored_normal == pytest.approx(0.50)
        assert unfavored_normal == pytest.approx(0.30)
        assert favored_rescued == pytest.approx(0.28)
        assert unfavored_rescued == pytest.approx(0.168)
