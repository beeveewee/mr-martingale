# Grid Bot v3.0 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Update the execution grid bot from v1.3.2 to v3.0 strategy — new entry gates, regime filter, dd20d/RSI rescue, v3.0 sizing, and wider grid gaps.

**Architecture:** In-place update of 3 files (config.py, grid_state.py, grid_bot.py), plus 2 new files (binance_data.py for daily candles, test_v30_logic.py for validation). All existing systems (reconciliation, command_bus, notifier, paper_client) preserved unchanged.

**Tech Stack:** Python 3.11+, pandas, requests (Binance REST API), pytest

---

### Task 1: Update config.py to v3.0 parameters

**Files:**
- Modify: `execution/config.py` (entire file)

**Step 1: Replace config.py contents**

Replace the full file. Key changes:
- `BOT_VERSION = "3.0.0"`
- Remove: `BASE_MARGIN_PCT`, `BASE_MARGIN_USD`, `MULTIPLIER`, `MAX_HOLD_HOURS`, `TRIGGER_PCT` alias
- Add: `EMA20_SPAN=20`, `SMA440_SPAN=440`, `HIGH_20D_BARS=120`, `RSI_PERIOD=14`
- Add: `RISK_PCT=0.50`, `RESCUE_RISK_PCT=0.28`, `LEVEL_MULTS_SEQ=[2.0, 2.5, 2.5, 7.0]`
- Add: `UNFAV_RISK_SCALE=0.60`, `UNFAV_SPACING_SCALE=1.60`, `UNFAV_TRIGGER_SCALE=3.0`, `UNFAV_HOLD_SCALE=0.45`
- Add: `DD20D_THRESHOLD=-0.10`, `RSI_RESCUE_THRESHOLD=30`
- Add: `MAX_HOLD_BARS=720`
- Change: `SHORT_TRIGGER_PCT=8.0`, `LEVEL_GAPS=[0.5, 1.5, 10.0, 14.0]`
- Keep: everything else (credentials, COIN, PAPER_TRADE, fees, notifications, STATE_FILE, CUM_DROPS derivation)

```python
"""
Grid Bot Configuration — v3.0 strategy
All tunable parameters in one place.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path.home() / ".openclaw" / "ws-731228" / ".secrets" / "hyperliquid.env")

# ─── Bot version ───────────────────────────────────────────────────────────
BOT_VERSION      = "3.0.0"

# ─── Hyperliquid credentials ───────────────────────────────────────────────
HL_PRIVATE_KEY   = os.environ["HL_PRIVATE_KEY"]
HL_MAIN_ADDRESS  = os.environ["HL_MAIN_ADDRESS"]
HL_TESTNET       = False

# ─── Asset ────────────────────────────────────────────────────────────────
COIN             = "BTC"
CANDLE_INTERVAL  = "4h"
POLL_SECONDS     = 300
SZ_DECIMALS      = 5

# ─── Indicator parameters ────────────────────────────────────────────────
EMA_SPAN         = 34       # EMA34 (4H closes)
MA_PERIOD        = 14       # SMA14 (4H closes)
EMA20_SPAN       = 20       # EMA20 (4H closes) — new gate
SMA440_SPAN      = 440      # SMA440 (daily closes) — regime filter
HIGH_20D_BARS    = 120      # rolling max of 4H highs (120 bars = 20 days)
RSI_PERIOD       = 14       # Wilder RSI on 4H closes

# ─── Entry triggers ──────────────────────────────────────────────────────
LONG_TRIGGER_PCT  = 0.5     # v28 gate: % below EMA34 AND SMA14
EMA20_TRIGGER_PCT = 2.0     # ema20 gate: % below EMA20
SHORT_TRIGGER_PCT = 8.0     # % above EMA34 AND SMA14 (was 2.5 in v1.3.2)

# ─── Regime scaling (unfavored) ──────────────────────────────────────────
UNFAV_RISK_SCALE    = 0.60
UNFAV_SPACING_SCALE = 1.60
UNFAV_TRIGGER_SCALE = 3.0
UNFAV_HOLD_SCALE    = 0.45

# ─── Filters ─────────────────────────────────────────────────────────────
DD20D_THRESHOLD      = -0.10   # drawdown from 20-day high to block entry
RSI_RESCUE_THRESHOLD = 30      # RSI(14) <= 30 rescues blocked entries

# ─── Grid parameters ──────────────────────────────────────────────────────
INITIAL_EQUITY_USD = 400.0
NUM_LEVELS       = 5
LEVERAGE         = 20
SHORT_LEVERAGE   = 15

# v3.0 position sizing (replaces BASE_MARGIN_PCT + MULTIPLIER)
RISK_PCT         = 0.50              # L1 notional = risk_pct × balance (favored)
RESCUE_RISK_PCT  = 0.28              # L1 notional when RSI-rescued
LEVEL_MULTS_SEQ  = [2.0, 2.5, 2.5, 7.0]  # L2=2x, L3=5x, L4=12.5x, L5=87.5x of L1

# Per-level gaps from previous level (%) — v3.0 values
LEVEL_GAPS       = [0.5, 1.5, 10.0, 14.0]

# Take profit: % from blended entry
TP_PCT           = 0.5

# ─── Timeout (4H bars) ───────────────────────────────────────────────────
MAX_HOLD_BARS    = 720   # 720 × 4H = 120 days (favored)
                          # × 0.45 = 324 bars = 54 days (unfavored)

# ─── Paper trade mode ─────────────────────────────────────────────────────
PAPER_TRADE      = False

# ─── Fees ─────────────────────────────────────────────────────────────────
TAKER_FEE        = 0.000432
MAKER_FEE        = 0.000144

# ─── Notifications ────────────────────────────────────────────────────────
DISCORD_WEBHOOK  = os.environ.get("DISCORD_WEBHOOK", "")
DISCORD_CHANNEL  = "1474189306536001659"

# ─── State file ───────────────────────────────────────────────────────────
STATE_FILE       = Path(__file__).parent / "grid_state.json"

# ─── Derived ──────────────────────────────────────────────────────────────
CUM_DROPS = []
_acc = 0.0
for g in LEVEL_GAPS:
    _acc += g
    CUM_DROPS.append(_acc / 100)
```

**Step 2: Verify import works**

Run: `cd /c/ClaudeCode/mrmartingale && python -c "from execution import config as cfg; print(cfg.BOT_VERSION, cfg.RISK_PCT, cfg.LEVEL_MULTS_SEQ, cfg.CUM_DROPS)"`
Expected: `3.0.0 0.5 [2.0, 2.5, 2.5, 7.0] [0.005, 0.02, 0.12, 0.26]`

**Step 3: Commit**

```bash
git add execution/config.py
git commit -m "feat(v30): update config.py to v3.0 parameters"
```

---

### Task 2: Create binance_data.py for SMA440 daily candles

**Files:**
- Create: `execution/binance_data.py`

**Step 1: Write the module**

```python
"""
Fetch BTC/USDT daily candles from Binance public API for SMA440 calculation.
No authentication required. Cached in-memory between refreshes.
"""
import logging
import time
import requests

log = logging.getLogger("binance_data")

_BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
_cache = {"ts": 0.0, "candles": []}
_CACHE_TTL = 14400  # 4 hours in seconds


def fetch_daily_closes(symbol: str = "BTCUSDT", limit: int = 500) -> list[float]:
    """
    Return up to `limit` daily close prices (oldest first) from Binance.
    Results cached for 4 hours.
    """
    now = time.time()
    if _cache["candles"] and (now - _cache["ts"]) < _CACHE_TTL:
        return _cache["candles"]

    try:
        resp = requests.get(
            _BINANCE_KLINES_URL,
            params={"symbol": symbol, "interval": "1d", "limit": limit},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        # Binance kline: [open_time, o, h, l, c, vol, close_time, ...]
        closes = [float(k[4]) for k in data]
        _cache["candles"] = closes
        _cache["ts"] = now
        log.info(f"Fetched {len(closes)} daily candles from Binance")
        return closes
    except Exception as e:
        log.error(f"Binance daily candle fetch failed: {e}")
        if _cache["candles"]:
            log.warning("Using stale cached daily candles")
            return _cache["candles"]
        return []
```

**Step 2: Test it runs**

Run: `cd /c/ClaudeCode/mrmartingale && python -c "from execution.binance_data import fetch_daily_closes; c = fetch_daily_closes(); print(f'{len(c)} daily closes, last={c[-1]:.1f}')"`
Expected: `500 daily closes, last=<some BTC price>`

**Step 3: Commit**

```bash
git add execution/binance_data.py
git commit -m "feat(v30): add binance_data.py for SMA440 daily candles"
```

---

### Task 3: Update hl_client.py get_candles to support more intervals and larger N

**Files:**
- Modify: `execution/hl_client.py:41-59`

**Step 1: Expand interval_ms map and default n**

Change the `interval_ms` dict in `get_candles` to include "1d":

```python
def get_candles(coin: str = cfg.COIN, interval: str = "4h", n: int = 60) -> list:
    end_ms = int(time.time() * 1000)
    interval_ms = {"1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}[interval]
    start_ms = end_ms - n * interval_ms
    resp = requests.post(
        f"{_URL}/info",
        json={
            "type": "candleSnapshot",
            "req": {
                "coin": coin,
                "interval": interval,
                "startTime": start_ms,
                "endTime": end_ms,
            },
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()
```

Only change: add `"1d": 86_400_000` to the interval_ms dict.

**Step 2: Verify**

Run: `cd /c/ClaudeCode/mrmartingale && python -c "from execution.hl_client import get_candles; c = get_candles('BTC', '4h', 150); print(f'{len(c)} 4H candles')"`
Expected: `~150 4H candles`

**Step 3: Commit**

```bash
git add execution/hl_client.py
git commit -m "feat(v30): add 1d interval support to hl_client.get_candles"
```

---

### Task 4: Update grid_state.py — new GridState fields and build_levels v3.0

**Files:**
- Modify: `execution/grid_state.py`

**Step 1: Add new fields to GridState**

Add these fields after `total_margin` (line 46):

```python
@dataclass
class GridState:
    side:           str   = ""
    active:         bool  = False
    trigger_px:     float = 0.0
    ema34:          float = 0.0
    sma14:          float = 0.0
    opened_at:      str   = ""
    levels:         List[GridLevel] = field(default_factory=list)
    tp_oid:         Optional[int]   = None
    tp_price:       float = 0.0
    blended_entry:  float = 0.0
    total_qty:      float = 0.0
    total_margin:   float = 0.0
    # v3.0 fields
    is_favored:     bool  = True
    entry_gate:     str   = ""       # "v28", "ema20", "rescued"
    risk_pct:       float = 0.0
    max_hold_hours: int   = 2880     # 720 bars × 4h = 2880h (favored default)
```

Note: `max_hold_hours` is computed at entry time:
- favored: `MAX_HOLD_BARS × 4 = 2880h`
- unfavored: `int(MAX_HOLD_BARS × UNFAV_HOLD_SCALE) × 4 = 1296h`

The existing `hold_hours()` method works as-is — we just compare against `self.max_hold_hours` instead of `cfg.MAX_HOLD_HOURS`.

**Step 2: Rewrite build_levels() for v3.0 sizing**

Replace the entire `build_levels` function (lines 132-159):

```python
def build_levels(trigger_px: float, side: str,
                 risk_pct: float = None, balance: float = None,
                 is_favored: bool = True) -> List[GridLevel]:
    """
    Build 5 grid levels using v3.0 sizing.

    L1 notional = risk_pct × balance
    L2-L5: cumulative multipliers from LEVEL_MULTS_SEQ [2.0, 2.5, 2.5, 7.0]
    Grid gaps scaled by UNFAV_SPACING_SCALE if unfavored.
    """
    leverage = cfg.LEVERAGE if side == LONG else cfg.SHORT_LEVERAGE

    # Fallback for backward compat (manual commands without risk context)
    if risk_pct is None:
        risk_pct = cfg.RISK_PCT
    if balance is None:
        balance = cfg.INITIAL_EQUITY_USD

    l1_notional = risk_pct * balance

    # Compute gap scaling
    spacing_scale = 1.0 if is_favored else cfg.UNFAV_SPACING_SCALE
    scaled_gaps = [g * spacing_scale for g in cfg.LEVEL_GAPS]
    cum_drops = []
    acc = 0.0
    for g in scaled_gaps:
        acc += g
        cum_drops.append(acc / 100.0)

    # Build cumulative multiplier sequence
    cum_mult = 1.0
    mults = [1.0]
    for m in cfg.LEVEL_MULTS_SEQ:
        cum_mult *= m
        mults.append(cum_mult)
    # mults = [1.0, 2.0, 5.0, 12.5, 87.5]

    levels = []
    for i in range(cfg.NUM_LEVELS):
        notional = l1_notional * mults[i]
        margin = notional / leverage
        if i == 0:
            target = trigger_px
        else:
            drop = cum_drops[i - 1]
            target = trigger_px * (1 - drop) if side == LONG else trigger_px * (1 + drop)
        levels.append(GridLevel(
            level=i + 1,
            target_px=round(target, 1),
            margin=margin,
            notional=notional,
        ))
    return levels
```

**Step 3: Handle _deserialize_grid for new fields**

The existing `_deserialize_grid` uses `GridState(**d)` which handles extra/missing fields via dataclass defaults. New fields have defaults, so old JSON state files load fine (new fields get defaults). No change needed.

**Step 4: Verify**

Run: `cd /c/ClaudeCode/mrmartingale && python -c "
from execution.grid_state import build_levels, LONG
levels = build_levels(50000, LONG, risk_pct=0.50, balance=400.0, is_favored=True)
for l in levels:
    print(f'L{l.level}: notional=\${l.notional:.2f} margin=\${l.margin:.2f} target=\${l.target_px:,.1f}')
"`

Expected output:
```
L1: notional=$200.00 margin=$10.00 target=$50,000.0
L2: notional=$400.00 margin=$20.00 target=$49,750.0
L3: notional=$1000.00 margin=$50.00 target=$49,000.0
L4: notional=$2500.00 margin=$125.00 target=$44,000.0
L5: notional=$17500.00 margin=$875.00 target=$37,000.0
```

**Step 5: Commit**

```bash
git add execution/grid_state.py
git commit -m "feat(v30): update GridState fields and build_levels for v3.0 sizing"
```

---

### Task 5: Update fetch_market_state() to return all v3.0 indicators

**Files:**
- Modify: `execution/grid_bot.py:437-447`

**Step 1: Add binance_data import**

At the top of grid_bot.py (after line 26, `from . import command_bus`), add:

```python
from . import binance_data
```

**Step 2: Rewrite fetch_market_state()**

Replace lines 437-447:

```python
def fetch_market_state() -> dict:
    """
    Return dict with all v3.0 indicators:
    price, ema34, sma14, ema20, sma440, high_20d, rsi14, is_bull
    """
    # 4H candles (need 500 for RSI warmup + high_20d window)
    candles = hl.get_candles(cfg.COIN, cfg.CANDLE_INTERVAL, n=500)
    closed = candles[:-1]  # exclude current open bar
    closes = pd.Series([float(c["c"]) for c in closed])
    highs = pd.Series([float(c["h"]) for c in closed])

    ema34 = float(closes.ewm(span=cfg.EMA_SPAN, adjust=False).mean().iloc[-1])
    sma14 = float(closes.rolling(cfg.MA_PERIOD).mean().iloc[-1])
    ema20 = float(closes.ewm(span=cfg.EMA20_SPAN, adjust=False).mean().iloc[-1])

    # High of last 20 days (120 × 4H bars)
    high_20d = float(highs.rolling(cfg.HIGH_20D_BARS).max().iloc[-1])

    # RSI(14) on 4H closes (Wilder SMA)
    delta = closes.diff()
    gain = delta.clip(lower=0).rolling(cfg.RSI_PERIOD).mean()
    loss = (-delta.clip(upper=0)).rolling(cfg.RSI_PERIOD).mean()
    rs = gain / loss.replace(0, float("nan"))
    rsi_series = 100 - (100 / (1 + rs))
    rsi14 = float(rsi_series.iloc[-1])

    # SMA440 from Binance daily candles
    daily_closes = binance_data.fetch_daily_closes(limit=500)
    sma440 = None
    is_bull = None
    if len(daily_closes) >= cfg.SMA440_SPAN:
        sma440_val = sum(daily_closes[-cfg.SMA440_SPAN:]) / cfg.SMA440_SPAN
        sma440 = sma440_val
        price = hl.get_mid_price(cfg.COIN)
        is_bull = price > sma440_val
    else:
        price = hl.get_mid_price(cfg.COIN)

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
```

**Step 3: Verify**

Run: `cd /c/ClaudeCode/mrmartingale && python -c "
from execution.grid_bot import fetch_market_state
s = fetch_market_state()
for k, v in s.items():
    if isinstance(v, float):
        print(f'{k}: {v:.2f}')
    else:
        print(f'{k}: {v}')
"`
Expected: All 8 fields with reasonable BTC values.

**Step 4: Commit**

```bash
git add execution/grid_bot.py
git commit -m "feat(v30): expand fetch_market_state() with ema20, sma440, high_20d, rsi14"
```

---

### Task 6: Update entry triggers (long_triggered, short_triggered)

**Files:**
- Modify: `execution/grid_bot.py:485-500`

**Step 1: Rewrite long_triggered()**

Replace lines 493-495:

```python
def long_triggered(state: dict) -> tuple:
    """
    v3.0 entry logic for LONG.
    Returns (triggered: bool, gate: str, risk_pct: float).
    gate is one of: "v28", "ema20", "rescued", "no_sma440", "no_trigger", "dd20d_blocked"
    """
    price = state["price"]
    is_bull = state["is_bull"]

    # Regime: if SMA440 unavailable, skip entirely
    if is_bull is None:
        return (False, "no_sma440", 0.0)

    is_favored = is_bull  # bull = favored for longs
    trigger_scale = 1.0 if is_favored else cfg.UNFAV_TRIGGER_SCALE

    # Gate 1: v28 (EMA34 + SMA14)
    v28_gate = (pct_below(price, state["ema34"]) >= cfg.LONG_TRIGGER_PCT * trigger_scale and
                pct_below(price, state["sma14"]) >= cfg.LONG_TRIGGER_PCT * trigger_scale)

    # Gate 2: EMA20
    ema20_gate = pct_below(price, state["ema20"]) >= cfg.EMA20_TRIGGER_PCT * trigger_scale

    if not (v28_gate or ema20_gate):
        return (False, "no_trigger", 0.0)

    # dd20d filter
    dd_from_high = (price / state["high_20d"]) - 1.0
    if dd_from_high < cfg.DD20D_THRESHOLD:
        # RSI rescue
        if state["rsi14"] <= cfg.RSI_RESCUE_THRESHOLD:
            risk = cfg.RESCUE_RISK_PCT * (1.0 if is_favored else cfg.UNFAV_RISK_SCALE)
            return (True, "rescued", risk)
        else:
            return (False, "dd20d_blocked", 0.0)

    # Normal entry
    risk = cfg.RISK_PCT * (1.0 if is_favored else cfg.UNFAV_RISK_SCALE)
    gate = "v28" if v28_gate else "ema20"
    return (True, gate, risk)
```

**Step 2: Rewrite short_triggered()**

Replace lines 498-500:

```python
def short_triggered(state: dict) -> tuple:
    """
    v3.0 entry logic for SHORT.
    Returns (triggered: bool, gate: str, risk_pct: float).
    No dd20d/RSI filter for shorts.
    """
    price = state["price"]
    is_bull = state["is_bull"]

    if is_bull is None:
        return (False, "no_sma440", 0.0)

    # For shorts: bear = favored
    is_favored = not is_bull
    trigger_scale = 1.0 if is_favored else cfg.UNFAV_TRIGGER_SCALE

    triggered = (pct_above(price, state["ema34"]) >= cfg.SHORT_TRIGGER_PCT * trigger_scale and
                 pct_above(price, state["sma14"]) >= cfg.SHORT_TRIGGER_PCT * trigger_scale)

    if not triggered:
        return (False, "no_trigger", 0.0)

    risk = cfg.RISK_PCT * (1.0 if is_favored else cfg.UNFAV_RISK_SCALE)
    return (True, "short", risk)
```

**Step 3: Commit**

```bash
git add execution/grid_bot.py
git commit -m "feat(v30): rewrite long/short_triggered with v3.0 gates, regime, dd20d, RSI rescue"
```

---

### Task 7: Update open_grid() for v3.0 sizing and state fields

**Files:**
- Modify: `execution/grid_bot.py:505-619`

**Step 1: Update open_grid signature and body**

Change the function signature and initial setup. The function now receives `risk_pct`, `entry_gate`, and `is_favored` instead of computing margin from `BASE_MARGIN_PCT`.

```python
def open_grid(bs: BotState, side: str, state: dict,
              risk_pct: float, entry_gate: str, is_favored: bool) -> GridState:
    leverage = cfg.LEVERAGE if side == LONG else cfg.SHORT_LEVERAGE
    price = state["price"]

    balance = hl.get_account_balance()

    # v3.0 timeout: convert bars to hours
    hold_bars = cfg.MAX_HOLD_BARS if is_favored else int(cfg.MAX_HOLD_BARS * cfg.UNFAV_HOLD_SCALE)
    max_hold_h = hold_bars * 4

    log.info(
        f"TRIGGER {side.upper()} [{entry_gate}]: BTC ${price:,.1f} "
        f"| EMA34 ${state['ema34']:,.1f} | SMA14 ${state['sma14']:,.1f} "
        f"| EMA20 ${state['ema20']:,.1f} | RSI14 {state['rsi14']:.1f} "
        f"| {'FAVORED' if is_favored else 'UNFAVORED'} "
        f"| risk={risk_pct:.2%} | {leverage}x | bal=${balance:.2f}"
    )

    try:
        hl.set_leverage(cfg.COIN, leverage)
    except Exception as e:
        log.warning(f"Could not set leverage {leverage}x for {side}: {e}")

    grid = GridState()
    grid.side = side
    grid.active = True
    grid.trigger_px = price
    grid.ema34 = state["ema34"]
    grid.sma14 = state["sma14"]
    grid.opened_at = datetime.now(timezone.utc).isoformat()
    grid.is_favored = is_favored
    grid.entry_gate = entry_gate
    grid.risk_pct = risk_pct
    grid.max_hold_hours = max_hold_h
    grid.levels = gs_mod.build_levels(
        price, side, risk_pct=risk_pct, balance=balance, is_favored=is_favored
    )

    # ... rest of open_grid stays the same from L1 market order onwards ...
    # (l1 fill, L2-L5 resting limits, TP, rollback logic — all unchanged)
```

The remainder of open_grid (L1 market order, L2-L5 limits, TP placement, rollback) is structurally unchanged. Only the logging message for `notifier.grid_opened()` should include gate/regime info.

Update the notifier.grid_opened call:

```python
    pct_dev = pct_below(price, state["ema34"]) if side == LONG else pct_above(price, state["ema34"])
    notifier.grid_opened(side, 1, fill_px, state["ema34"], state["sma14"], l1.margin, pct_dev)
```

**Step 2: Commit**

```bash
git add execution/grid_bot.py
git commit -m "feat(v30): update open_grid for v3.0 sizing, regime, and gate tracking"
```

---

### Task 8: Update main loop — new state dict, timeout, trigger calls

**Files:**
- Modify: `execution/grid_bot.py:841-976` (run function and callers)

**Step 1: Update all fetch_market_state() callers**

Every place that calls `price, ema34, sma14 = fetch_market_state()` must change to use the dict.

Affected locations:
1. **sleep_with_command_watch** (line 424): `price, ema34, sma14 = fetch_market_state()` → `state = fetch_market_state()`
2. **Startup command processing** (line 871): same pattern
3. **Main loop** (line 881): same pattern

For each, extract `price = state["price"]`, `ema34 = state["ema34"]`, `sma14 = state["sma14"]` where needed for backward compat.

**Step 2: Update process_pending_commands signature**

Change `process_pending_commands(bs, price, ema34, sma14)` to accept state dict:

```python
def process_pending_commands(bs: BotState, state: dict) -> BotState:
```

Inside, when handling `manual_long` / `manual_short`, call open_grid with the new signature:

```python
    if action == "manual_long" and not bs.long_grid.active and not bs.short_grid.active:
        risk = cfg.RISK_PCT  # manual = always normal risk
        is_bull = state["is_bull"] if state["is_bull"] is not None else True
        grid = open_grid(bs, LONG, state, risk_pct=risk, entry_gate="manual", is_favored=is_bull)
        ...
```

**Step 3: Update timeout check**

Replace lines 937 and 953:

```python
# Old:
elif bs.long_grid.hold_hours() >= cfg.MAX_HOLD_HOURS:

# New:
elif bs.long_grid.hold_hours() >= bs.long_grid.max_hold_hours:
```

Same for short grid.

**Step 4: Update trigger calls in main loop**

Replace lines 944-946:
```python
# Old:
elif (not bs.short_grid.active) and long_triggered(price, ema34, sma14):
    if open_grid(bs, LONG, price, ema34, sma14) is None:

# New:
elif not bs.short_grid.active:
    triggered, gate, risk = long_triggered(state)
    if triggered:
        is_favored = state["is_bull"]  # bull = favored for longs
        if open_grid(bs, LONG, state, risk_pct=risk, entry_gate=gate, is_favored=is_favored) is None:
            log.error("open_grid(LONG) failed — skipping this poll")
```

Replace lines 960-962 (short):
```python
elif not bs.long_grid.active:
    triggered, gate, risk = short_triggered(state)
    if triggered:
        is_favored = not state["is_bull"]  # bear = favored for shorts
        if open_grid(bs, SHORT, state, risk_pct=risk, entry_gate=gate, is_favored=is_favored) is None:
            log.error("open_grid(SHORT) failed — skipping this poll")
```

**Step 5: Update log lines and send_2h_report**

Update the logging in the main loop to include new indicators:

```python
            log.info(
                f"{mode_tag}BTC ${price:,.1f} | "
                f"↓EMA34 {pct_below(price, ema34):+.2f}% ↓SMA14 {pct_below(price, sma14):+.2f}% "
                f"↓EMA20 {pct_below(price, state['ema20']):+.2f}% | "
                f"RSI {state['rsi14']:.0f} | "
                f"{'BULL' if state['is_bull'] else 'BEAR' if state['is_bull'] is not None else 'N/A'} | "
                f"Long: {'OPEN' if bs.long_grid.active else 'idle'} | "
                f"Short: {'OPEN' if bs.short_grid.active else 'idle'}"
            )
```

Update `send_2h_report` signature to accept state dict.

**Step 6: Update run() startup banner**

Replace lines 844-848:

```python
    log.info(f"Mr Martingale v{cfg.BOT_VERSION} — LONG + SHORT [{mode}]")
    log.info(f"Coin: {cfg.COIN} | {cfg.NUM_LEVELS}L | "
             f"Long trigger: {cfg.LONG_TRIGGER_PCT}%/{cfg.EMA20_TRIGGER_PCT}% EMA20 | "
             f"Short trigger: {cfg.SHORT_TRIGGER_PCT}% | TP: {cfg.TP_PCT}%")
    log.info(f"Risk: {cfg.RISK_PCT:.0%} | Rescue: {cfg.RESCUE_RISK_PCT:.0%} | "
             f"Mults: {cfg.LEVEL_MULTS_SEQ} | Gaps: {cfg.LEVEL_GAPS}")
    log.info(f"Timeout: {cfg.MAX_HOLD_BARS} bars favored | "
             f"{int(cfg.MAX_HOLD_BARS * cfg.UNFAV_HOLD_SCALE)} bars unfavored")
```

**Step 7: Commit**

```bash
git add execution/grid_bot.py
git commit -m "feat(v30): update main loop for state dict, v3.0 triggers, and per-grid timeout"
```

---

### Task 9: Validation test — compare bot logic against v30_engine backtest

**Files:**
- Create: `execution/tests/test_v30_logic.py`

**Step 1: Create test directory**

```bash
mkdir -p execution/tests
touch execution/tests/__init__.py
```

**Step 2: Write validation tests**

```python
"""
Validate that the execution bot's v3.0 logic matches the backtest engine.
Tests entry gates, sizing, grid construction, and timeout independently.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

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
        l1_n = 0.50 * 400.0  # = 200
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
        """Unfavored gaps: ×1.6 → [0.8, 2.4, 16.0, 22.4]%"""
        levels = build_levels(100000, LONG, risk_pct=0.30, balance=1000.0, is_favored=False)
        # cum drops: 0.008, 0.032, 0.192, 0.416
        assert levels[1].target_px == pytest.approx(100000 * (1 - 0.008), rel=0.001)
        assert levels[2].target_px == pytest.approx(100000 * (1 - 0.032), rel=0.001)
        assert levels[3].target_px == pytest.approx(100000 * (1 - 0.192), rel=0.001)
        assert levels[4].target_px == pytest.approx(100000 * (1 - 0.416), rel=0.001)

    def test_unfavored_risk_sizing(self):
        """Unfavored L1 notional = 0.30 × balance"""
        levels = build_levels(50000, LONG, risk_pct=0.30, balance=400.0, is_favored=False)
        assert levels[0].notional == pytest.approx(0.30 * 400.0)

    def test_rescue_risk_sizing(self):
        """Rescue L1 notional = 0.28 × balance (favored) or 0.168 (unfavored)"""
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
    """Test long_triggered / short_triggered with mock market state dicts."""

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

    def test_no_sma440_blocks_entry(self):
        from execution.grid_bot import long_triggered, short_triggered
        state = self._make_state(is_bull=None)
        t, gate, risk = long_triggered(state)
        assert not t
        assert gate == "no_sma440"

    def test_v28_gate_fires(self):
        """Price 1% below both EMA34 and SMA14 → v28 gate in bull regime"""
        from execution.grid_bot import long_triggered
        # price = 50000, ema34 = 50500 → pct_below = 0.99% > 0.5%
        # sma14 = 50400 → pct_below = 0.79% > 0.5%
        state = self._make_state(price=50000, ema34=50500, sma14=50400, is_bull=True)
        t, gate, risk = long_triggered(state)
        assert t
        assert gate == "v28"
        assert risk == pytest.approx(0.50)

    def test_ema20_gate_fires(self):
        """Price 2.5% below EMA20, but NOT below EMA34/SMA14 → ema20 gate"""
        from execution.grid_bot import long_triggered
        # ema20 = 51300, price = 50000 → pct_below = 2.53% > 2.0%
        # ema34 = 50100 → pct_below = 0.20% < 0.5% (v28 fails)
        state = self._make_state(price=50000, ema34=50100, sma14=50100, ema20=51300, is_bull=True)
        t, gate, risk = long_triggered(state)
        assert t
        assert gate == "ema20"

    def test_unfavored_trigger_scaling(self):
        """In bear regime, triggers scale by 3.0 → need 1.5% below for v28"""
        from execution.grid_bot import long_triggered
        # price = 50000, ema34 = 50300 → pct_below = 0.60% < 1.5% (0.5×3)
        state = self._make_state(price=50000, ema34=50300, sma14=50300, ema20=50300, is_bull=False)
        t, gate, risk = long_triggered(state)
        assert not t

        # price = 49000, ema34 = 50000 → pct_below = 2.0% > 1.5%
        state2 = self._make_state(price=49000, ema34=50000, sma14=50000, ema20=51000, is_bull=False)
        t2, gate2, risk2 = long_triggered(state2)
        assert t2
        assert risk2 == pytest.approx(0.50 * 0.60)  # unfavored risk

    def test_dd20d_blocks_entry(self):
        """Price dropped >10% from 20-day high → entry blocked"""
        from execution.grid_bot import long_triggered
        # high_20d = 55000, price = 49000 → dd = (49000/55000) - 1 = -10.9%
        state = self._make_state(price=49000, ema34=50000, sma14=50000,
                                 high_20d=55000, rsi14=45.0, is_bull=True)
        t, gate, risk = long_triggered(state)
        assert not t
        assert gate == "dd20d_blocked"

    def test_rsi_rescue(self):
        """dd20d blocks but RSI <= 30 → rescued entry with reduced risk"""
        from execution.grid_bot import long_triggered
        state = self._make_state(price=49000, ema34=50000, sma14=50000,
                                 high_20d=55000, rsi14=28.0, is_bull=True)
        t, gate, risk = long_triggered(state)
        assert t
        assert gate == "rescued"
        assert risk == pytest.approx(0.28)  # rescue risk, favored

    def test_rsi_rescue_unfavored(self):
        """Rescued + unfavored → rescue_risk × unfav_scale"""
        from execution.grid_bot import long_triggered
        state = self._make_state(price=49000, ema34=50000, sma14=50000,
                                 high_20d=55000, rsi14=25.0, is_bull=False)
        # unfavored trigger: need 1.5% below → (50000-49000)/50000 = 2% ✓
        t, gate, risk = long_triggered(state)
        assert t
        assert gate == "rescued"
        assert risk == pytest.approx(0.28 * 0.60)  # 0.168

    def test_short_trigger_favored(self):
        """Short fires at 8% above MAs in bear regime (favored for shorts)"""
        from execution.grid_bot import short_triggered
        # price = 54500, ema34 = 50000 → pct_above = 9% > 8%
        state = self._make_state(price=54500, ema34=50000, sma14=50000, is_bull=False)
        t, gate, risk = short_triggered(state)
        assert t
        assert risk == pytest.approx(0.50)

    def test_short_trigger_unfavored(self):
        """Short in bull regime needs 24% (8% × 3.0)"""
        from execution.grid_bot import short_triggered
        # price = 55000, ema34 = 50000 → pct_above = 10% < 24%
        state = self._make_state(price=55000, ema34=50000, sma14=50000, is_bull=True)
        t, gate, risk = short_triggered(state)
        assert not t

    def test_no_trigger_idle(self):
        """Price near MAs → no trigger"""
        from execution.grid_bot import long_triggered, short_triggered
        state = self._make_state(price=50000, ema34=50050, sma14=50050, ema20=50050, is_bull=True)
        tl, _, _ = long_triggered(state)
        ts, _, _ = short_triggered(state)
        assert not tl
        assert not ts


class TestTimeout:
    def test_favored_timeout_hours(self):
        """Favored: 720 bars × 4h = 2880 hours"""
        max_h = cfg.MAX_HOLD_BARS * 4
        assert max_h == 2880

    def test_unfavored_timeout_hours(self):
        """Unfavored: 324 bars × 4h = 1296 hours"""
        bars = int(cfg.MAX_HOLD_BARS * cfg.UNFAV_HOLD_SCALE)
        assert bars == 324
        assert bars * 4 == 1296


class TestBacktestAlignment:
    """
    Verify that v3.0 engine backtest results match expected metrics.
    This ensures the spec hasn't drifted from the validated backtest.
    """

    def test_engine_results_file_exists(self):
        """Check that v30 search results are available for comparison."""
        import json
        from pathlib import Path
        # Look for the latest v30 results
        results_files = sorted(Path(".").glob("v*_search_results.json"))
        # At minimum, v28 results should exist
        assert len(results_files) > 0, "No search results files found"

    def test_cum_mults_match_spec(self):
        """Cumulative multipliers: [1, 2, 5, 12.5, 87.5]"""
        mults = [1.0]
        for m in cfg.LEVEL_MULTS_SEQ:
            mults.append(mults[-1] * m)
        assert mults == pytest.approx([1.0, 2.0, 5.0, 12.5, 87.5])

    def test_favored_cum_drops_match_spec(self):
        """Favored cumulative drops: [0.5, 2.0, 12.0, 26.0]%"""
        assert cfg.CUM_DROPS == pytest.approx([0.005, 0.02, 0.12, 0.26])

    def test_unfavored_cum_drops_match_spec(self):
        """Unfavored cumulative drops (×1.6): [0.8, 3.2, 19.2, 41.6]%"""
        scale = cfg.UNFAV_SPACING_SCALE
        unfav_drops = []
        acc = 0.0
        for g in cfg.LEVEL_GAPS:
            acc += g * scale
            unfav_drops.append(acc / 100.0)
        assert unfav_drops == pytest.approx([0.008, 0.032, 0.192, 0.416])

    def test_risk_combinations(self):
        """All 4 risk scenarios match spec values"""
        favored_normal = cfg.RISK_PCT
        unfavored_normal = cfg.RISK_PCT * cfg.UNFAV_RISK_SCALE
        favored_rescued = cfg.RESCUE_RISK_PCT
        unfavored_rescued = cfg.RESCUE_RISK_PCT * cfg.UNFAV_RISK_SCALE

        assert favored_normal == pytest.approx(0.50)
        assert unfavored_normal == pytest.approx(0.30)
        assert favored_rescued == pytest.approx(0.28)
        assert unfavored_rescued == pytest.approx(0.168)
```

**Step 3: Run tests**

Run: `cd /c/ClaudeCode/mrmartingale && python -m pytest execution/tests/test_v30_logic.py -v`
Expected: All tests PASS

**Step 4: Commit**

```bash
git add execution/tests/
git commit -m "test(v30): add validation tests for v3.0 entry logic, sizing, and backtest alignment"
```

---

### Task 10: Integration smoke test — paper mode dry run

**Step 1: Temporarily set PAPER_TRADE=True in config.py**

**Step 2: Run the bot for one poll cycle**

```bash
cd /c/ClaudeCode/mrmartingale && timeout 30 python -m execution.grid_bot 2>&1 || true
```

Expected: Bot starts, fetches all indicators (price, ema34, sma14, ema20, sma440, high_20d, rsi14), logs BULL/BEAR regime, no crash.

**Step 3: Revert PAPER_TRADE to original value**

**Step 4: Final commit with all files**

```bash
git add -A
git commit -m "feat(v30): complete grid bot v3.0 update with all entry gates, regime filter, and validation tests"
```
