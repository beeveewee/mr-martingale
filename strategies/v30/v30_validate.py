"""
MRM v3.0 — Engine Validation
==============================
Verifies that the v3.0 engine reproduces v2.8 and v2.9 results exactly.

Expected:
  v2.8: 85.6% CAGR, 0 liqs, 889 trades (dd20d OFF, RSI rescue OFF)
  v2.9: 119.1% CAGR, 0 liqs, 1505 trades (dd20d ON, RSI rescue ON)
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from v30_indicators import load_data
from v30_engine import run_backtest
import numpy as np


def v28_entry(ind, px, prev_candle, is_bull):
    """Replicate v2.8 EMA34+SMA14 entry gate."""
    ema = ind['ema34'][prev_candle]
    sma = ind['sma14'][prev_candle]
    if np.isnan(ema) or np.isnan(sma):
        return False
    trigger = 0.005 if is_bull else 0.015
    pct_below_ema = (ema - px) / ema
    pct_below_sma = (sma - px) / sma
    return pct_below_ema >= trigger and pct_below_sma >= trigger


def sma440_regime(ind, px, prev_candle, sma440_val):
    """Standard SMA440 regime."""
    if sma440_val is None or (isinstance(sma440_val, float) and np.isnan(sma440_val)):
        return True
    return px > sma440_val


if __name__ == '__main__':
    data = load_data()

    # v2.8 baseline: dd20d ON, RSI rescue OFF (v2.8 always has dd20d)
    print("\n=== v2.8 Validation (dd20d ON, RSI rescue OFF) ===")
    r28 = run_backtest(data, v28_entry, sma440_regime,
                       config={'use_dd20d': True, 'use_rsi_rescue': False},
                       label='v28_baseline')
    print(f"  CAGR: {r28['cagr']}%  (expected: 85.6%)")
    print(f"  Liqs: {r28['liq']}  (expected: 0)")
    print(f"  Trades: {r28['trades']}  (expected: 889)")
    print(f"  Final eq: ${r28['final_eq']:,.0f}")
    print(f"  Levels: {r28['levels']}")

    ok28 = r28['cagr'] == 85.6 and r28['liq'] == 0 and r28['trades'] == 889
    print(f"  {'PASS' if ok28 else 'FAIL'}")

    # v2.9 baseline: dd20d ON, RSI rescue ON
    print("\n=== v2.9 Validation (dd20d ON, RSI rescue ON) ===")
    r29 = run_backtest(data, v28_entry, sma440_regime,
                       config={'use_dd20d': True, 'use_rsi_rescue': True},
                       label='v29_baseline')
    print(f"  CAGR: {r29['cagr']}%  (expected: 119.1%)")
    print(f"  Liqs: {r29['liq']}  (expected: 0)")
    print(f"  Trades: {r29['trades']}  (expected: 1505)")
    print(f"  Final eq: ${r29['final_eq']:,.0f}")
    print(f"  Filtered: {r29['filtered']}  Rescued: {r29['rescued']}")
    print(f"  Levels: {r29['levels']}")

    ok29 = r29['cagr'] == 119.1 and r29['liq'] == 0 and r29['trades'] == 1505
    print(f"  {'PASS' if ok29 else 'FAIL'}")

    print(f"\n{'='*50}")
    if ok28 and ok29:
        print("ALL VALIDATIONS PASSED — engine is correct.")
    else:
        print("VALIDATION FAILED — engine needs debugging.")
        if not ok28:
            print(f"  v2.8: got CAGR={r28['cagr']}, liqs={r28['liq']}, trades={r28['trades']}")
        if not ok29:
            print(f"  v2.9: got CAGR={r29['cagr']}, liqs={r29['liq']}, trades={r29['trades']}")
    sys.exit(0 if (ok28 and ok29) else 1)
