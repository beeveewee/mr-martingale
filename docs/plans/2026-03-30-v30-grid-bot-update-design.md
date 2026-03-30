# Grid Bot v3.0 Update Design

**Date:** 2026-03-30
**Approach:** In-place update of execution/grid_bot.py, config.py, grid_state.py

## Changes Summary

### 1. config.py — Full Parameter Replacement

```
BOT_VERSION = "3.0.0"

# Entry gates
LONG_TRIGGER_PCT = 0.5       # v28 gate (EMA34+SMA14)
EMA20_TRIGGER_PCT = 2.0      # NEW ema20 gate
SHORT_TRIGGER_PCT = 8.0      # was 2.5

# Indicators
EMA_SPAN = 34
MA_PERIOD = 14
EMA20_SPAN = 20              # NEW
SMA440_SPAN = 440            # NEW (daily candles)
HIGH_20D_BARS = 120          # NEW (4H bars = 20 days)
RSI_PERIOD = 14              # NEW

# Regime scaling (unfavored)
UNFAV_RISK_SCALE = 0.60
UNFAV_SPACING_SCALE = 1.60
UNFAV_TRIGGER_SCALE = 3.0
UNFAV_HOLD_SCALE = 0.45

# Position sizing (replaces BASE_MARGIN_PCT + MULTIPLIER)
RISK_PCT = 0.50
RESCUE_RISK_PCT = 0.28
LEVEL_MULTS_SEQ = [2.0, 2.5, 2.5, 7.0]

# Grid gaps (replaces [0.5, 1.5, 3.0, 3.0])
LEVEL_GAPS = [0.5, 1.5, 10.0, 14.0]

# Filters
DD20D_THRESHOLD = -0.10
RSI_RESCUE_THRESHOLD = 30

# Timeout (replaces MAX_HOLD_HOURS=120)
MAX_HOLD_BARS = 720          # 4H bars = 120 days favored
                              # × 0.45 = 324 bars = 54 days unfavored
```

### 2. fetch_market_state() — Returns Dict

Old: `(price, ema34, sma14)` from 60 4H candles.

New: dict with all v3.0 indicators:
- 4H candles (500 from Hyperliquid): ema34, sma14, ema20, rsi14, high_20d
- Daily candles (500 from Binance public API): sma440, is_bull
- Daily data cached in memory, refreshed every 4H boundary

### 3. New File: execution/binance_data.py

Fetches daily BTCUSDT candles from Binance REST API (no auth).
`fetch_daily_candles(limit=500) -> List[dict]`
Cached between 4H refreshes.

### 4. Entry Logic

`long_triggered(state)` returns `(triggered, gate_name, risk_pct)`:
1. Regime check: if sma440 unavailable → skip
2. v28 gate OR ema20 gate (with unfavored trigger scaling)
3. dd20d filter: blocks if price dropped >10% from 20-day high
4. RSI rescue: if blocked by dd20d and RSI(14) <= 30 → enter with rescue_risk

`short_triggered(state)` returns `(triggered, risk_pct)`:
- 8% above EMA34 AND SMA14 (favored=bear), 24% if unfavored
- No dd20d/RSI filter for shorts

### 5. build_levels() — New Sizing

`risk_pct × balance` for L1, then cumulative mults_seq:
- L1=1x, L2=2x, L3=5x, L4=12.5x, L5=87.5x of L1 notional
- Grid gaps scaled by UNFAV_SPACING_SCALE if unfavored

### 6. Timeout — Wall-Clock Conversion

Convert 4H bars to hours for simplicity:
- Favored: 720 × 4 = 2880 hours
- Unfavored: 324 × 4 = 1296 hours
- GridState tracks `is_favored` to determine which timeout applies

### 7. GridState New Fields

- `is_favored: bool` — regime at entry
- `entry_gate: str` — "v28" | "ema20" | "rescued"
- `risk_pct: float` — actual risk used
- `max_hold_hours: int` — timeout for this position

### 8. Validation Test

Run v30_engine.py backtest and compare key metrics against expected:
- CAGR ~125.3%, liquidations = 0, trades ~1515
- Verify the execution bot's entry logic matches engine decisions
  on a sample of candle data (unit test with mock market state)

### Preserved Systems

- paper_client.py: no changes (same interface)
- reconciliation: unchanged (still matches exchange state)
- command_bus: unchanged (manual_long/short/close)
- notifier: updated messages to include gate/regime info
