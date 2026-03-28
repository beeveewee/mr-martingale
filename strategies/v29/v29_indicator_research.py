"""
MRM v2.9 — Indicator Research
==============================
Tests additional indicators from Swing v5/v6 PineScript strategies as
entry/exit filters to improve on v2.8 baseline (85.6% CAGR, 0 liqs, 889 trades).

Indicators tested:
  1. Stochastic RSI — momentum extremes filter (replace/supplement dd20d)
  2. Span B — Ichimoku-style midline as regime filter
  3. Chandelier Stop — ATR-based trailing as entry gate
  4. Donchian Channel — rolling N-bar low as crash filter
  5. Gaussian Channel — SMA + ATR bands as volatility filter
  6. Relaxed dd20d — loosen threshold to recover blocked entries

Base: backtest_v28.py engine with all cost model, 1m liq checks.
"""
import pandas as pd, numpy as np, time, json, os, sys

# ── Data loading (shared with backtest_v28.py) ────────────────────────────
print("Loading data...")
DATA_PATH = os.path.join(os.path.dirname(__file__), '..', '..',
    'signals', 'multi_asset_results', 'btcusdt_binance_1m_2017_2026.parquet')
DATA_PATH = os.path.normpath(DATA_PATH)
df = pd.read_parquet(DATA_PATH).sort_values('ts').reset_index(drop=True)
n = len(df)

# 4H bars + base indicators
df['t4h'] = df['ts'].dt.floor('4h')
c4 = df.groupby('t4h').agg(
    o=('o', 'first'), h=('h', 'max'), l=('l', 'min'), c=('c', 'last')
).sort_index()
c4['ema34'] = c4['c'].ewm(span=34, adjust=False).mean()
c4['sma14'] = c4['c'].rolling(14).mean()
c4['high_20d'] = c4['h'].rolling(120).max()  # 120 x 4H = 20 days

# ── Additional indicator computations on 4H bars ─────────────────────────

# 1. Stochastic RSI (on 4H hlcc4)
def compute_stoch_rsi(closes, highs, lows, rsi_len=14, stoch_len=14, smooth_k=3):
    """Compute Stochastic RSI K value on 4H bars."""
    hlcc4 = (highs + lows + closes + closes) / 4.0
    delta = hlcc4.diff()
    gain = delta.clip(lower=0).rolling(rsi_len).mean()
    loss = (-delta.clip(upper=0)).rolling(rsi_len).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    # Stochastic of RSI
    rsi_min = rsi.rolling(stoch_len).min()
    rsi_max = rsi.rolling(stoch_len).max()
    stoch_raw = 100 * (rsi - rsi_min) / (rsi_max - rsi_min).replace(0, np.nan)
    k = stoch_raw.rolling(smooth_k).mean()
    return k

# 2. Span B (midline of N-bar range)
def compute_span_b(highs, lows, period=120):
    """Ichimoku-style Span B: midpoint of N-bar high/low range."""
    hh = highs.rolling(period).max()
    ll = lows.rolling(period).min()
    return (hh + ll) / 2.0

# 3. Chandelier Stop (highest high - ATR * mult)
def compute_chandelier(highs, lows, closes, period=22, mult=3.0):
    """Chandelier exit: highest_high(N) - mult * ATR(N)."""
    hh = highs.rolling(period).max()
    # True Range
    prev_close = closes.shift(1)
    tr = pd.concat([
        highs - lows,
        (highs - prev_close).abs(),
        (lows - prev_close).abs()
    ], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    return hh - mult * atr

# 4. Donchian low (N-bar lowest low — alternative crash filter)
def compute_donchian_low(lows, period=120):
    """Rolling N-bar lowest low."""
    return lows.rolling(period).min()

# 5. Gaussian Channel (SMA + ATR bands)
def compute_gaussian_channel(closes, highs, lows, period=91, mult=0.75):
    """Gaussian channel: SMA(period) +/- mult * SMA(TR, period)."""
    prev_close = closes.shift(1)
    tr = pd.concat([
        highs - lows,
        (highs - prev_close).abs(),
        (lows - prev_close).abs()
    ], axis=1).max(axis=1)
    mid = closes.rolling(period).mean()
    tr_avg = tr.rolling(period).mean()
    upper = mid + mult * tr_avg
    lower = mid - mult * tr_avg
    return mid, upper, lower

# 6. ATR (for various volatility filters)
def compute_atr(highs, lows, closes, period=14):
    prev_close = closes.shift(1)
    tr = pd.concat([
        highs - lows,
        (highs - prev_close).abs(),
        (lows - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()

# Pre-compute all indicators with various periods
print("Computing indicators...")
c4h, c4l, c4c = c4['h'], c4['l'], c4['c']

# Stochastic RSI variants
for rsi_l in [7, 11, 14]:
    for stoch_l in [7, 14, 18]:
        for sk in [3, 10, 20]:
            key = f'stoch_k_{rsi_l}_{stoch_l}_{sk}'
            c4[key] = compute_stoch_rsi(c4c, c4h, c4l, rsi_l, stoch_l, sk)

# Span B variants
for p in [60, 120, 180, 240, 350]:
    c4[f'span_b_{p}'] = compute_span_b(c4h, c4l, p)

# Chandelier variants
for p in [22, 44, 71]:
    for m in [2.0, 3.0, 3.9]:
        c4[f'chand_{p}_{m}'] = compute_chandelier(c4h, c4l, c4c, p, m)

# Donchian low variants
for p in [60, 90, 120, 180]:
    c4[f'don_low_{p}'] = compute_donchian_low(c4l, p)

# Gaussian channel variants
for p in [60, 91, 150, 266]:
    for m in [0.75, 1.0, 1.5, 1.9]:
        mid, upper, lower = compute_gaussian_channel(c4c, c4h, c4l, p, m)
        c4[f'gauss_lower_{p}_{m}'] = lower
        c4[f'gauss_upper_{p}_{m}'] = upper

# ATR variants
for p in [14, 22, 44]:
    c4[f'atr_{p}'] = compute_atr(c4h, c4l, c4c, p)

# Rolling high variants (for relaxed dd20d)
for bars in [60, 90, 120, 180]:
    c4[f'high_{bars}'] = c4h.rolling(bars).max()

print(f"Indicator columns: {len(c4.columns)}")

# Convert to numpy for speed
ema_v = c4['ema34'].values
sma_v = c4['sma14'].values
high_20d_v = c4['high_20d'].values
c4_dict = {col: c4[col].values for col in c4.columns}

# Daily SMA440
df['t1d'] = df['ts'].dt.floor('1D')
cd = df.groupby('t1d').agg(c=('c', 'last')).sort_index()
cd['sma440'] = cd['c'].rolling(440).mean()
sma440_map = {k: v for k, v in zip(cd.index.values, cd['sma440'].values)}

# 1m arrays
ts_arr = df['ts'].values
h_arr = df['h'].values
l_arr = df['l'].values
c_arr = df['c'].values
t4v = df['t4h'].values

# 4H boundary index
bounds = [0]
for i in range(1, n):
    if t4v[i] != t4v[i - 1]:
        bounds.append(i)
bounds = np.array(bounds)
bar_to_candle = np.zeros(n, dtype=np.int64)
for bi in range(len(bounds)):
    s_ = bounds[bi]
    e_ = bounds[bi + 1] if bi + 1 < len(bounds) else n
    bar_to_candle[s_:e_] = bi

# Simulation window
SIM_START = pd.Timestamp('2018-10-31', tz='UTC')
SIM_END = pd.Timestamp('2026-03-28 23:59:59', tz='UTC')
sim_idx = np.searchsorted(ts_arr, np.datetime64(SIM_START.asm8))
sim_end_idx = np.searchsorted(ts_arr, np.datetime64(SIM_END.asm8))
print(f"Data: {n:,} bars | Sim: {SIM_START.date()} to {SIM_END.date()}")

# ── v2.8 base parameters ──────────────────────────────────────────────────
BASE_PARAMS = dict(
    risk_pct=0.50, tp_pct=0.005,
    level_gaps=[0.5, 1.5, 10.0, 14.0],
    level_mults_seq=[2.0, 2.5, 2.5, 7.0],
    max_levels=5, long_trigger_pct=0.005, short_trigger_pct=0.08,
    unfav_trigger_scale=3.0, unfav_risk_scale=0.60,
    unfav_spacing_scale=1.60, unfav_hold_scale=0.45,
    max_hold_bars=720, min_equity=50,
    # Cost model
    comm=0.00045, taker=0.000432, maker=0.000144,
    fund_8h=0.000013, slip=0.03, maint=0.005,
)

NOT_MULTS = [1.0]
_m = 1.0
for x in BASE_PARAMS['level_mults_seq']:
    _m *= x
    NOT_MULTS.append(_m)


def cum_drops(gaps):
    result, acc = [], 0.0
    for g in gaps:
        acc += g
        result.append(acc / 100.0)
    return result


def run_backtest(filter_fn, label="", params=None):
    """
    Run full backtest with a custom entry filter function.

    filter_fn(prev_candle, px, direction, c4_dict) -> bool
        Returns True to SKIP (block) the entry, False to allow it.
    """
    p = {**BASE_PARAMS}
    if params:
        p.update(params)

    balance = 1000.0
    n_tp = n_to = n_liq = 0
    active = False
    direction = None
    favored = None
    levels = []
    drops = []
    max_hold = 0
    entry_candle = 0
    cooldown_until = 0
    peak_equity = 1000.0
    max_drawdown = 0.0
    level_dist = {}
    long_count = short_count = fav_count = unfav_count = filtered_count = 0
    liq_events = []
    monthly = {}

    for i in range(min(n, sim_end_idx + 1)):
        ci = bar_to_candle[i]
        is_boundary = (i == bounds[ci])

        # Equity tracking
        if i >= sim_idx:
            equity = balance
            if active and levels:
                total_qty = sum(lv[3] for lv in levels)
                blended = sum(lv[3] * lv[1] for lv in levels) / total_qty
                equity = balance + total_qty * (c_arr[i] - blended)
            if equity > peak_equity:
                peak_equity = equity
            dd = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0
            if dd > max_drawdown:
                max_drawdown = dd
            tp_ = pd.Timestamp(ts_arr[i])
            k = (tp_.year, tp_.month)
            if k not in monthly:
                monthly[k] = {'s': equity, 'e': equity}
            monthly[k]['e'] = equity

        # Active position management
        if active:
            total_qty = sum(lv[3] for lv in levels)
            blended = sum(lv[3] * lv[1] for lv in levels) / total_qty
            total_notional = sum(lv[2] for lv in levels)

            # Liquidation check
            worst_px = l_arr[i] if direction == 'long' else h_arr[i]
            unrealized = total_qty * (worst_px - blended)
            if balance + unrealized <= total_notional * p['maint']:
                n_liq += 1
                liq_events.append(f"{pd.Timestamp(ts_arr[i])} {direction} L{len(levels)} eq=${balance:,.0f}")
                balance = 1000.0
                active = False
                levels = []
                cooldown_until = ci + 1
                peak_equity = 1000.0
                continue

            # Grid fills
            if len(levels) < p['max_levels']:
                for li in range(len(levels), p['max_levels']):
                    if li - 1 >= len(drops):
                        break
                    l1_price = levels[0][1]
                    drop_pct = drops[li - 1]
                    if direction == 'long':
                        fill_trigger = l1_price * (1 - drop_pct)
                        hit = l_arr[i] <= fill_trigger
                    else:
                        fill_trigger = l1_price * (1 + drop_pct)
                        hit = h_arr[i] >= fill_trigger
                    if hit:
                        fill_px = (fill_trigger - p['slip']) if direction == 'long' else (fill_trigger + p['slip'])
                        lv_notional = levels[0][2] * NOT_MULTS[li]
                        lv_qty = lv_notional / fill_px if direction == 'long' else -lv_notional / fill_px
                        fee_in = lv_notional * (p['maker'] + p['comm'])
                        balance -= fee_in
                        levels.append((li + 1, fill_px, lv_notional, lv_qty, i))
                        break

            # Recompute after potential fill
            total_qty = sum(lv[3] for lv in levels)
            blended = sum(lv[3] * lv[1] for lv in levels) / total_qty
            total_notional = sum(lv[2] for lv in levels)

            # Take-profit
            best_px = h_arr[i] if direction == 'long' else l_arr[i]
            tp_price = blended * (1 + p['tp_pct']) if direction == 'long' else blended * (1 - p['tp_pct'])
            tp_hit = best_px >= tp_price if direction == 'long' else best_px <= tp_price

            if tp_hit:
                exit_px = (tp_price - p['slip']) if direction == 'long' else (tp_price + p['slip'])
                fee_out = total_notional * (p['maker'] + p['comm'])
                hold_minutes = i - levels[0][4]
                funding = total_notional * p['fund_8h'] * (hold_minutes / (8 * 60))
                gross_pnl = total_qty * (exit_px - blended)
                pnl = gross_pnl - fee_out - funding
                balance += pnl
                n_tp += 1
                nl = len(levels)
                level_dist[nl] = level_dist.get(nl, 0) + 1
                if direction == 'long': long_count += 1
                else: short_count += 1
                if favored: fav_count += 1
                else: unfav_count += 1
                if i >= sim_idx and k in monthly:
                    monthly[k]['e'] = balance
                active = False
                levels = []
                cooldown_until = ci + 1
                continue

            # Timeout
            if is_boundary and (ci - entry_candle) >= max_hold:
                exit_px = (c_arr[i] - p['slip']) if direction == 'long' else (c_arr[i] + p['slip'])
                fee_out = total_notional * (p['taker'] + p['comm'])
                hold_minutes = i - levels[0][4]
                funding = total_notional * p['fund_8h'] * (hold_minutes / (8 * 60))
                gross_pnl = total_qty * (exit_px - blended)
                pnl = gross_pnl - fee_out - funding
                balance += pnl
                n_to += 1
                nl = len(levels)
                level_dist[nl] = level_dist.get(nl, 0) + 1
                if direction == 'long': long_count += 1
                else: short_count += 1
                if favored: fav_count += 1
                else: unfav_count += 1
                active = False
                levels = []
                cooldown_until = ci + 1
                continue

        # Entry logic (4H boundary only)
        if is_boundary and not active:
            if i < sim_idx or ci < cooldown_until or balance < p['min_equity'] or ci < 1:
                continue
            prev_candle = ci - 1
            if prev_candle >= len(ema_v):
                continue
            ema_val = ema_v[prev_candle]
            sma_val = sma_v[prev_candle]
            if np.isnan(ema_val) or np.isnan(sma_val):
                continue

            px = c_arr[i]
            day_ts = np.datetime64(pd.Timestamp(ts_arr[i]).normalize().asm8)
            s440 = sma440_map.get(day_ts)
            if s440 is None or np.isnan(s440):
                s440 = sma440_map.get(day_ts - np.timedelta64(1, 'D'))
            if s440 is None or (isinstance(s440, float) and np.isnan(s440)):
                continue

            is_bull = px > s440
            pct_below_ema = (ema_val - px) / ema_val
            pct_below_sma = (sma_val - px) / sma_val
            pct_above_ema = (px - ema_val) / ema_val
            pct_above_sma = (px - sma_val) / sma_val
            entered = False

            # LONG entry
            long_favored = is_bull
            trigger = p['long_trigger_pct'] if long_favored else p['long_trigger_pct'] * p['unfav_trigger_scale']
            risk = p['risk_pct'] if long_favored else p['risk_pct'] * p['unfav_risk_scale']
            hold = p['max_hold_bars'] if long_favored else int(p['max_hold_bars'] * p['unfav_hold_scale'])
            gaps = p['level_gaps'] if long_favored else [g * p['unfav_spacing_scale'] for g in p['level_gaps']]

            if pct_below_ema >= trigger and pct_below_sma >= trigger:
                # Apply the custom filter
                skip = filter_fn(prev_candle, px, 'long', c4_dict)
                if skip:
                    filtered_count += 1

                if not skip:
                    entry_px = px + p['slip']
                    notional = risk * balance
                    qty = notional / entry_px
                    fee_in = notional * (p['taker'] + p['comm'])
                    balance -= fee_in
                    levels = [(1, entry_px, notional, qty, i)]
                    direction = 'long'
                    favored = long_favored
                    drops = cum_drops(gaps)
                    max_hold = hold
                    entry_candle = ci
                    active = True
                    entered = True

            # SHORT entry
            if not entered:
                short_favored = not is_bull
                trigger = p['short_trigger_pct'] if short_favored else p['short_trigger_pct'] * p['unfav_trigger_scale']
                risk = p['risk_pct'] if short_favored else p['risk_pct'] * p['unfav_risk_scale']
                hold = p['max_hold_bars'] if short_favored else int(p['max_hold_bars'] * p['unfav_hold_scale'])
                gaps = p['level_gaps'] if short_favored else [g * p['unfav_spacing_scale'] for g in p['level_gaps']]

                if pct_above_ema >= trigger and pct_above_sma >= trigger:
                    entry_px = px - p['slip']
                    notional = risk * balance
                    qty = -notional / entry_px
                    fee_in = notional * (p['taker'] + p['comm'])
                    balance -= fee_in
                    levels = [(1, entry_px, notional, qty, i)]
                    direction = 'short'
                    favored = short_favored
                    drops = cum_drops(gaps)
                    max_hold = hold
                    entry_candle = ci
                    active = True

    # Compute stats
    total = n_tp + n_to + n_liq
    yrs = (SIM_END - SIM_START).days / 365.25
    cagr = ((balance / 1000) ** (1 / yrs) - 1) if balance > 0 else -1.0

    sorted_months = sorted(monthly.keys())
    n_months = len(sorted_months)
    prod = 1.0
    for ym in sorted_months:
        d = monthly[ym]
        r = d['e'] / d['s'] if d['s'] > 0 else 1
        prod *= r
    cmr = prod ** (1 / n_months) - 1 if n_months > 0 else 0

    return {
        'label': label,
        'cagr': round(cagr * 100, 1),
        'cmr': round(cmr * 100, 2),
        'max_dd': round(max_drawdown * 100, 1),
        'trades': total,
        'tp': n_tp, 'to': n_to, 'liq': n_liq,
        'longs': long_count, 'shorts': short_count,
        'fav': fav_count, 'unfav': unfav_count,
        'filtered': filtered_count,
        'final_eq': round(balance, 0),
        'total_return': round(balance / 1000, 1),
        'levels': dict(sorted(level_dist.items())),
        'liq_events': liq_events,
    }


# ── Filter functions ──────────────────────────────────────────────────────

def dd20d_baseline(prev_candle, px, direction, c4d):
    """v2.8 baseline: block when price >10% below 20d high."""
    if direction != 'long':
        return False
    h20 = c4d['high_20d'][prev_candle] if prev_candle < len(c4d['high_20d']) else np.nan
    if np.isnan(h20) or h20 <= 0:
        return False
    return (px / h20 - 1) < -0.10


def make_dd_filter(threshold, window_bars=120):
    """Parameterized drawdown-from-high filter."""
    key = f'high_{window_bars}'
    def filt(prev_candle, px, direction, c4d):
        if direction != 'long':
            return False
        h = c4d[key][prev_candle] if prev_candle < len(c4d[key]) else np.nan
        if np.isnan(h) or h <= 0:
            return False
        return (px / h - 1) < threshold
    return filt


def make_stoch_rsi_filter(rsi_len, stoch_len, smooth_k, mode='block_mid'):
    """
    Stochastic RSI filter.
    mode='block_mid': block entries when K is in the middle (not extreme) — only enter at extremes
    mode='block_overbought': block entries when K >= 80 (overbought)
    mode='require_oversold': only enter when K <= 20 (oversold)
    """
    key = f'stoch_k_{rsi_len}_{stoch_len}_{smooth_k}'
    def filt(prev_candle, px, direction, c4d):
        if direction != 'long':
            return False
        k_val = c4d[key][prev_candle] if prev_candle < len(c4d[key]) else np.nan
        if np.isnan(k_val):
            return False
        if mode == 'block_mid':
            return 20 < k_val < 80  # only allow extremes
        elif mode == 'block_overbought':
            return k_val >= 80
        elif mode == 'require_oversold':
            return k_val > 20  # only enter when oversold
        return False
    return filt


def make_span_b_filter(period):
    """Block long entries when price is below Span B (bearish regime)."""
    key = f'span_b_{period}'
    def filt(prev_candle, px, direction, c4d):
        if direction != 'long':
            return False
        sb = c4d[key][prev_candle] if prev_candle < len(c4d[key]) else np.nan
        if np.isnan(sb):
            return False
        return px < sb
    return filt


def make_chandelier_filter(period, mult):
    """Block long entries when price is below chandelier stop."""
    key = f'chand_{period}_{mult}'
    def filt(prev_candle, px, direction, c4d):
        if direction != 'long':
            return False
        cs = c4d[key][prev_candle] if prev_candle < len(c4d[key]) else np.nan
        if np.isnan(cs):
            return False
        return px < cs
    return filt


def make_gaussian_filter(period, mult):
    """Block long entries when price is below Gaussian lower band."""
    key = f'gauss_lower_{period}_{mult}'
    def filt(prev_candle, px, direction, c4d):
        if direction != 'long':
            return False
        lb = c4d[key][prev_candle] if prev_candle < len(c4d[key]) else np.nan
        if np.isnan(lb):
            return False
        return px < lb
    return filt


def make_donchian_filter(period, threshold_pct):
    """Block entries when price is >threshold_pct below Donchian low (deep crash)."""
    key = f'don_low_{period}'
    def filt(prev_candle, px, direction, c4d):
        if direction != 'long':
            return False
        dl = c4d[key][prev_candle] if prev_candle < len(c4d[key]) else np.nan
        if np.isnan(dl) or dl <= 0:
            return False
        # Price below Donchian low = recent low broken = crash
        return px < dl * (1 - threshold_pct)
    return filt


def make_combined_filter(*filters):
    """Combine multiple filters: skip if ANY filter says skip."""
    def filt(prev_candle, px, direction, c4d):
        for f in filters:
            if f(prev_candle, px, direction, c4d):
                return True
        return False
    return filt


def no_filter(prev_candle, px, direction, c4d):
    """No filter at all — baseline without dd20d."""
    return False


# ── Phase 1: Single indicator tests ──────────────────────────────────────
print("\n" + "=" * 90)
print("  PHASE 1: SINGLE INDICATOR TESTS")
print("=" * 90)

configs = []

# 0. Baseline (v2.8 dd20d at -10%)
configs.append(("v2.8 baseline (dd20d -10%)", dd20d_baseline))

# 0b. No filter at all (to see what dd20d costs us)
configs.append(("NO filter", no_filter))

# 1. Relaxed dd20d thresholds
for thresh in [-0.08, -0.12, -0.15, -0.20]:
    configs.append((f"dd20d {thresh*100:.0f}%", make_dd_filter(thresh, 120)))

# 2. Different window sizes for dd filter
for window in [60, 90, 180]:
    configs.append((f"dd {window//6}d -10%", make_dd_filter(-0.10, window)))

# 3. Stochastic RSI variants
for rsi_l, stoch_l, sk in [(14, 14, 3), (11, 7, 20), (7, 18, 10)]:
    for mode in ['block_overbought', 'require_oversold']:
        configs.append((f"StochRSI({rsi_l},{stoch_l},{sk}) {mode}",
                        make_stoch_rsi_filter(rsi_l, stoch_l, sk, mode)))

# 4. Span B variants
for p in [120, 240, 350]:
    configs.append((f"SpanB({p})", make_span_b_filter(p)))

# 5. Chandelier variants
for p, m in [(22, 3.0), (44, 2.0), (71, 3.9)]:
    configs.append((f"Chandelier({p},{m})", make_chandelier_filter(p, m)))

# 6. Gaussian lower band
for p, m in [(91, 1.5), (150, 1.0), (266, 1.9)]:
    configs.append((f"Gaussian({p},{m})", make_gaussian_filter(p, m)))

# 7. Donchian crash filter
for p in [60, 120]:
    for t in [0.0, 0.05]:
        configs.append((f"Donchian({p}, -{t*100:.0f}%)", make_donchian_filter(p, t)))

results = []
for label, filt in configs:
    t0 = time.time()
    r = run_backtest(filt, label)
    elapsed = time.time() - t0
    r['time'] = round(elapsed, 1)
    results.append(r)
    liq_str = f" LIQ={r['liq']}" if r['liq'] > 0 else ""
    print(f"  {label:<45} CAGR={r['cagr']:>6.1f}%  CMR={r['cmr']:>5.2f}%  "
          f"MaxDD={r['max_dd']:>5.1f}%  Trades={r['trades']:>5}{liq_str}  [{elapsed:.0f}s]")

# Save Phase 1 results
out_path = os.path.join(os.path.dirname(__file__), 'v29_phase1_results.json')
with open(out_path, 'w') as f:
    json.dump(results, f, indent=2)
print(f"\nPhase 1 results saved to {out_path}")

# ── Phase 2: Combinations of best single filters ─────────────────────────
print("\n" + "=" * 90)
print("  PHASE 2: INDICATOR COMBINATIONS")
print("=" * 90)

# We'll combine dd20d with the best-performing supplementary filters
combo_configs = []

# dd20d + StochRSI (block overbought)
for rsi_l, stoch_l, sk in [(14, 14, 3), (11, 7, 20)]:
    combo_configs.append((
        f"dd20d-10% + StochRSI({rsi_l},{stoch_l},{sk}) block_OB",
        make_combined_filter(
            dd20d_baseline,
            make_stoch_rsi_filter(rsi_l, stoch_l, sk, 'block_overbought')
        )
    ))

# dd20d + Span B
for p in [120, 240]:
    combo_configs.append((
        f"dd20d-10% + SpanB({p})",
        make_combined_filter(dd20d_baseline, make_span_b_filter(p))
    ))

# dd20d + Chandelier
for p, m in [(22, 3.0), (44, 2.0)]:
    combo_configs.append((
        f"dd20d-10% + Chand({p},{m})",
        make_combined_filter(dd20d_baseline, make_chandelier_filter(p, m))
    ))

# dd20d + Gaussian lower band
for p, m in [(91, 1.5), (150, 1.0)]:
    combo_configs.append((
        f"dd20d-10% + Gauss({p},{m})",
        make_combined_filter(dd20d_baseline, make_gaussian_filter(p, m))
    ))

# Relaxed dd20d (-12%) + supplementary
for rsi_l, stoch_l, sk in [(14, 14, 3)]:
    combo_configs.append((
        f"dd20d-12% + StochRSI({rsi_l},{stoch_l},{sk}) block_OB",
        make_combined_filter(
            make_dd_filter(-0.12, 120),
            make_stoch_rsi_filter(rsi_l, stoch_l, sk, 'block_overbought')
        )
    ))

# Relaxed dd20d (-15%) + Chandelier (safety net)
combo_configs.append((
    "dd20d-15% + Chand(22,3.0)",
    make_combined_filter(
        make_dd_filter(-0.15, 120),
        make_chandelier_filter(22, 3.0)
    )
))

# Span B alone + Chandelier (no dd20d)
combo_configs.append((
    "SpanB(240) + Chand(44,2.0)",
    make_combined_filter(
        make_span_b_filter(240),
        make_chandelier_filter(44, 2.0)
    )
))

# Triple combo: relaxed dd20d + StochRSI + Chandelier
combo_configs.append((
    "dd20d-15% + StochRSI(14,14,3) OB + Chand(22,3)",
    make_combined_filter(
        make_dd_filter(-0.15, 120),
        make_stoch_rsi_filter(14, 14, 3, 'block_overbought'),
        make_chandelier_filter(22, 3.0)
    )
))

results2 = []
for label, filt in combo_configs:
    t0 = time.time()
    r = run_backtest(filt, label)
    elapsed = time.time() - t0
    r['time'] = round(elapsed, 1)
    results2.append(r)
    liq_str = f" LIQ={r['liq']}" if r['liq'] > 0 else ""
    print(f"  {label:<55} CAGR={r['cagr']:>6.1f}%  CMR={r['cmr']:>5.2f}%  "
          f"MaxDD={r['max_dd']:>5.1f}%  Trades={r['trades']:>5}{liq_str}  [{elapsed:.0f}s]")

# Save Phase 2 results
out_path = os.path.join(os.path.dirname(__file__), 'v29_phase2_results.json')
with open(out_path, 'w') as f:
    json.dump(results2, f, indent=2)
print(f"\nPhase 2 results saved to {out_path}")

# ── Phase 3: Risk tuning on best 0-liq configs ──────────────────────────
print("\n" + "=" * 90)
print("  PHASE 3: RISK TUNING ON BEST 0-LIQ CONFIGS")
print("=" * 90)

# Collect the best 0-liq configs that beat baseline CAGR
all_results = results + results2
zero_liq_winners = [r for r in all_results if r['liq'] == 0 and r['cagr'] > 85.6]

# If nothing beats baseline, take top 0-liq by CAGR
if not zero_liq_winners:
    zero_liq_candidates = sorted([r for r in all_results if r['liq'] == 0],
                                  key=lambda x: x['cagr'], reverse=True)[:5]
    print("  No 0-liq configs beat baseline CAGR. Testing risk tuning on top 5:")
else:
    zero_liq_candidates = sorted(zero_liq_winners, key=lambda x: x['cagr'], reverse=True)[:5]
    print(f"  Found {len(zero_liq_winners)} configs beating baseline. Testing risk tuning on top 5:")

for r in zero_liq_candidates:
    print(f"    {r['label']}: CAGR={r['cagr']}%, trades={r['trades']}")

# Re-run top configs with different risk levels
results3 = []
# Find the filter function for each winner
config_map = {label: filt for label, filt in configs + combo_configs}

for candidate in zero_liq_candidates:
    label_base = candidate['label']
    if label_base not in config_map:
        continue
    filt = config_map[label_base]

    for risk in [0.40, 0.46, 0.50, 0.52, 0.54, 0.56]:
        label = f"{label_base} | risk={risk}"
        t0 = time.time()
        r = run_backtest(filt, label, params={'risk_pct': risk})
        elapsed = time.time() - t0
        r['time'] = round(elapsed, 1)
        results3.append(r)
        liq_str = f" LIQ={r['liq']}" if r['liq'] > 0 else ""
        print(f"  {label:<60} CAGR={r['cagr']:>6.1f}%  MaxDD={r['max_dd']:>5.1f}%  "
              f"Trades={r['trades']:>5}{liq_str}")

# Save Phase 3 results
out_path = os.path.join(os.path.dirname(__file__), 'v29_phase3_results.json')
with open(out_path, 'w') as f:
    json.dump(results3, f, indent=2)
print(f"\nPhase 3 results saved to {out_path}")

# ── Summary ──────────────────────────────────────────────────────────────
print("\n" + "=" * 90)
print("  FINAL RANKING — ALL 0-LIQ CONFIGS BY CAGR")
print("=" * 90)

all_final = results + results2 + results3
zero_liq_all = sorted([r for r in all_final if r['liq'] == 0],
                       key=lambda x: x['cagr'], reverse=True)

print(f"\n  {'Rank':<5} {'Label':<60} {'CAGR':>7} {'CMR':>7} {'MaxDD':>7} {'Trades':>7}")
print(f"  {'-'*5} {'-'*60} {'-'*7} {'-'*7} {'-'*7} {'-'*7}")
for i, r in enumerate(zero_liq_all[:30], 1):
    marker = " <-- v2.8" if r['label'] == "v2.8 baseline (dd20d -10%)" else ""
    print(f"  {i:<5} {r['label']:<60} {r['cagr']:>6.1f}% {r['cmr']:>6.2f}% "
          f"{r['max_dd']:>6.1f}% {r['trades']:>7}{marker}")

# Save complete results
out_path = os.path.join(os.path.dirname(__file__), 'v29_all_results.json')
with open(out_path, 'w') as f:
    json.dump(all_final, f, indent=2)
print(f"\nAll results saved to {out_path}")
print("Done.")
