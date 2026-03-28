"""
MRM v2.9 — Phase 4: Rescue Filters
====================================
The dd20d filter blocks 2,180 entries (leaving 889). Many blocked entries
are probably safe. Can we use secondary indicators to "rescue" some?

Approach: dd20d blocks the entry, but if a secondary indicator confirms
the entry is safe, allow it anyway. This increases trade count while
hopefully maintaining 0 liquidations.

Also: try dynamic risk scaling — full risk when indicators are favorable,
reduced risk when dd20d would have blocked.
"""
import pandas as pd, numpy as np, time, json, os, sys

# ── Reuse data loading from main research script ─────────────────────────
print("Loading data...")
DATA_PATH = os.path.join(os.path.dirname(__file__), '..', '..',
    'signals', 'multi_asset_results', 'btcusdt_binance_1m_2017_2026.parquet')
DATA_PATH = os.path.normpath(DATA_PATH)
df = pd.read_parquet(DATA_PATH).sort_values('ts').reset_index(drop=True)
n = len(df)

df['t4h'] = df['ts'].dt.floor('4h')
c4 = df.groupby('t4h').agg(
    o=('o', 'first'), h=('h', 'max'), l=('l', 'min'), c=('c', 'last')
).sort_index()
c4['ema34'] = c4['c'].ewm(span=34, adjust=False).mean()
c4['sma14'] = c4['c'].rolling(14).mean()
c4['high_20d'] = c4['h'].rolling(120).max()

# Additional indicators
c4h, c4l, c4c = c4['h'], c4['l'], c4['c']

# Stochastic RSI
def compute_stoch_rsi(closes, highs, lows, rsi_len=14, stoch_len=14, smooth_k=3):
    hlcc4 = (highs + lows + closes + closes) / 4.0
    delta = hlcc4.diff()
    gain = delta.clip(lower=0).rolling(rsi_len).mean()
    loss = (-delta.clip(upper=0)).rolling(rsi_len).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi_min = rsi.rolling(stoch_len).min()
    rsi_max = rsi.rolling(stoch_len).max()
    stoch_raw = 100 * (rsi - rsi_min) / (rsi_max - rsi_min).replace(0, np.nan)
    return stoch_raw.rolling(smooth_k).mean()

# Span B
def compute_span_b(highs, lows, period):
    return (highs.rolling(period).max() + lows.rolling(period).min()) / 2.0

# Chandelier
def compute_chandelier(highs, lows, closes, period, mult):
    hh = highs.rolling(period).max()
    prev_close = closes.shift(1)
    tr = pd.concat([highs - lows, (highs - prev_close).abs(), (lows - prev_close).abs()], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    return hh - mult * atr

# ATR / volatility ratio
def compute_atr(highs, lows, closes, period):
    prev_close = closes.shift(1)
    tr = pd.concat([highs - lows, (highs - prev_close).abs(), (lows - prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()

# RSI
def compute_rsi(closes, period=14):
    delta = closes.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

# Compute all needed indicators
for rsi_l in [7, 11, 14]:
    for stoch_l in [7, 14, 18]:
        for sk in [3, 10, 20]:
            c4[f'stoch_k_{rsi_l}_{stoch_l}_{sk}'] = compute_stoch_rsi(c4c, c4h, c4l, rsi_l, stoch_l, sk)

for p in [60, 120, 180, 240, 350]:
    c4[f'span_b_{p}'] = compute_span_b(c4h, c4l, p)

for p in [22, 44]:
    for m in [2.0, 3.0]:
        c4[f'chand_{p}_{m}'] = compute_chandelier(c4h, c4l, c4c, p, m)

c4['atr_14'] = compute_atr(c4h, c4l, c4c, 14)
c4['atr_44'] = compute_atr(c4h, c4l, c4c, 44)
c4['rsi_14'] = compute_rsi(c4c, 14)
c4['rsi_7'] = compute_rsi(c4c, 7)

# Velocity: rate of decline
c4['velocity_6'] = c4c.pct_change(6)   # 1-day velocity on 4H
c4['velocity_24'] = c4c.pct_change(24)  # 4-day velocity

# ATR ratio (current ATR vs longer-term)
c4['atr_ratio'] = c4['atr_14'] / c4['atr_44']

# Distance from 20d high as continuous variable (for dynamic risk)
c4['dd_from_high'] = c4c / c4['high_20d'] - 1

print(f"Indicator columns: {len(c4.columns)}")

ema_v = c4['ema34'].values
sma_v = c4['sma14'].values
high_20d_v = c4['high_20d'].values
c4_dict = {col: c4[col].values for col in c4.columns}

df['t1d'] = df['ts'].dt.floor('1D')
cd = df.groupby('t1d').agg(c=('c', 'last')).sort_index()
cd['sma440'] = cd['c'].rolling(440).mean()
sma440_map = {k: v for k, v in zip(cd.index.values, cd['sma440'].values)}

ts_arr = df['ts'].values
h_arr = df['h'].values
l_arr = df['l'].values
c_arr = df['c'].values
t4v = df['t4h'].values

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

SIM_START = pd.Timestamp('2018-10-31', tz='UTC')
SIM_END = pd.Timestamp('2026-03-28 23:59:59', tz='UTC')
sim_idx = np.searchsorted(ts_arr, np.datetime64(SIM_START.asm8))
sim_end_idx = np.searchsorted(ts_arr, np.datetime64(SIM_END.asm8))
print(f"Data: {n:,} bars | Sim: {SIM_START.date()} to {SIM_END.date()}")

BASE_PARAMS = dict(
    risk_pct=0.50, tp_pct=0.005,
    level_gaps=[0.5, 1.5, 10.0, 14.0],
    level_mults_seq=[2.0, 2.5, 2.5, 7.0],
    max_levels=5, long_trigger_pct=0.005, short_trigger_pct=0.08,
    unfav_trigger_scale=3.0, unfav_risk_scale=0.60,
    unfav_spacing_scale=1.60, unfav_hold_scale=0.45,
    max_hold_bars=720, min_equity=50,
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


def run_backtest_dynamic(filter_fn, label="", params=None):
    """
    Run backtest with dynamic filter/risk function.

    filter_fn(prev_candle, px, direction, c4_dict) -> (skip: bool, risk_override: float or None)
        skip=True blocks entry entirely.
        risk_override replaces risk_pct for this entry if not None.
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
    rescued_count = 0
    liq_events = []
    monthly = {}

    for i in range(min(n, sim_end_idx + 1)):
        ci = bar_to_candle[i]
        is_boundary = (i == bounds[ci])

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

        if active:
            total_qty = sum(lv[3] for lv in levels)
            blended = sum(lv[3] * lv[1] for lv in levels) / total_qty
            total_notional = sum(lv[2] for lv in levels)

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

            total_qty = sum(lv[3] for lv in levels)
            blended = sum(lv[3] * lv[1] for lv in levels) / total_qty
            total_notional = sum(lv[2] for lv in levels)

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
                active = False
                levels = []
                cooldown_until = ci + 1
                continue

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

            long_favored = is_bull
            trigger = p['long_trigger_pct'] if long_favored else p['long_trigger_pct'] * p['unfav_trigger_scale']
            risk = p['risk_pct'] if long_favored else p['risk_pct'] * p['unfav_risk_scale']
            hold = p['max_hold_bars'] if long_favored else int(p['max_hold_bars'] * p['unfav_hold_scale'])
            gaps = p['level_gaps'] if long_favored else [g * p['unfav_spacing_scale'] for g in p['level_gaps']]

            if pct_below_ema >= trigger and pct_below_sma >= trigger:
                skip, risk_override = filter_fn(prev_candle, px, 'long', c4_dict)
                if skip:
                    filtered_count += 1
                else:
                    if risk_override is not None:
                        risk = risk_override if long_favored else risk_override * p['unfav_risk_scale']
                        rescued_count += 1

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
        'label': label, 'cagr': round(cagr * 100, 1),
        'cmr': round(cmr * 100, 2), 'max_dd': round(max_drawdown * 100, 1),
        'trades': total, 'tp': n_tp, 'to': n_to, 'liq': n_liq,
        'longs': long_count, 'shorts': short_count,
        'filtered': filtered_count, 'rescued': rescued_count,
        'final_eq': round(balance, 0), 'total_return': round(balance / 1000, 1),
        'levels': dict(sorted(level_dist.items())),
        'liq_events': liq_events,
    }


# ── Rescue filter functions ──────────────────────────────────────────────

def baseline_dd20d(prev_candle, px, direction, c4d):
    """v2.8 baseline."""
    if direction != 'long':
        return False, None
    h20 = c4d['high_20d'][prev_candle] if prev_candle < len(c4d['high_20d']) else np.nan
    if np.isnan(h20) or h20 <= 0:
        return False, None
    dd = (px / h20) - 1
    if dd < -0.10:
        return True, None
    return False, None


def make_rescue_by_rsi(rsi_key='rsi_14', oversold_thresh=30, rescue_risk=0.25):
    """
    dd20d blocks, but if RSI is oversold (bounce likely), allow with reduced risk.
    """
    def filt(prev_candle, px, direction, c4d):
        if direction != 'long':
            return False, None
        h20 = c4d['high_20d'][prev_candle] if prev_candle < len(c4d['high_20d']) else np.nan
        if np.isnan(h20) or h20 <= 0:
            return False, None
        dd = (px / h20) - 1
        if dd >= -0.10:
            return False, None  # not blocked by dd20d
        # dd20d would block. Check RSI for rescue.
        rsi = c4d[rsi_key][prev_candle] if prev_candle < len(c4d[rsi_key]) else np.nan
        if not np.isnan(rsi) and rsi <= oversold_thresh:
            return False, rescue_risk  # rescued with reduced risk
        return True, None  # blocked
    return filt


def make_rescue_by_velocity(vel_key='velocity_6', vel_thresh=-0.02, rescue_risk=0.25):
    """
    dd20d blocks, but if velocity is NOT strongly negative (decline slowing), allow with reduced risk.
    """
    def filt(prev_candle, px, direction, c4d):
        if direction != 'long':
            return False, None
        h20 = c4d['high_20d'][prev_candle] if prev_candle < len(c4d['high_20d']) else np.nan
        if np.isnan(h20) or h20 <= 0:
            return False, None
        dd = (px / h20) - 1
        if dd >= -0.10:
            return False, None
        vel = c4d[vel_key][prev_candle] if prev_candle < len(c4d[vel_key]) else np.nan
        if not np.isnan(vel) and vel >= vel_thresh:
            return False, rescue_risk
        return True, None
    return filt


def make_rescue_by_span_b(span_key='span_b_240', rescue_risk=0.25):
    """
    dd20d blocks, but if price is still above Span B (support held), allow with reduced risk.
    """
    def filt(prev_candle, px, direction, c4d):
        if direction != 'long':
            return False, None
        h20 = c4d['high_20d'][prev_candle] if prev_candle < len(c4d['high_20d']) else np.nan
        if np.isnan(h20) or h20 <= 0:
            return False, None
        dd = (px / h20) - 1
        if dd >= -0.10:
            return False, None
        sb = c4d[span_key][prev_candle] if prev_candle < len(c4d[span_key]) else np.nan
        if not np.isnan(sb) and px >= sb:
            return False, rescue_risk
        return True, None
    return filt


def make_rescue_by_atr_ratio(atr_thresh=1.5, rescue_risk=0.25):
    """
    dd20d blocks, but if ATR ratio is LOW (volatility subsiding), allow with reduced risk.
    """
    def filt(prev_candle, px, direction, c4d):
        if direction != 'long':
            return False, None
        h20 = c4d['high_20d'][prev_candle] if prev_candle < len(c4d['high_20d']) else np.nan
        if np.isnan(h20) or h20 <= 0:
            return False, None
        dd = (px / h20) - 1
        if dd >= -0.10:
            return False, None
        atr_r = c4d['atr_ratio'][prev_candle] if prev_candle < len(c4d['atr_ratio']) else np.nan
        if not np.isnan(atr_r) and atr_r <= atr_thresh:
            return False, rescue_risk
        return True, None
    return filt


def make_rescue_by_stoch_rsi(stoch_key='stoch_k_14_14_3', oversold_thresh=20, rescue_risk=0.25):
    """
    dd20d blocks, but if StochRSI K <= threshold (deeply oversold), allow with reduced risk.
    """
    def filt(prev_candle, px, direction, c4d):
        if direction != 'long':
            return False, None
        h20 = c4d['high_20d'][prev_candle] if prev_candle < len(c4d['high_20d']) else np.nan
        if np.isnan(h20) or h20 <= 0:
            return False, None
        dd = (px / h20) - 1
        if dd >= -0.10:
            return False, None
        k_val = c4d[stoch_key][prev_candle] if prev_candle < len(c4d[stoch_key]) else np.nan
        if not np.isnan(k_val) and k_val <= oversold_thresh:
            return False, rescue_risk
        return True, None
    return filt


def make_dynamic_risk_by_dd(dd_tiers=None):
    """
    Dynamic risk scaling based on drawdown from 20d high.
    No entries blocked entirely, but risk reduces as drawdown deepens.
    """
    if dd_tiers is None:
        dd_tiers = [
            (-0.10, None),    # above -10%: full risk
            (-0.15, 0.30),    # -10% to -15%: reduced risk
            (-0.25, 0.15),    # -15% to -25%: minimal risk
            (-1.00, None),    # below -25%: blocked (return skip=True)
        ]
    def filt(prev_candle, px, direction, c4d):
        if direction != 'long':
            return False, None
        h20 = c4d['high_20d'][prev_candle] if prev_candle < len(c4d['high_20d']) else np.nan
        if np.isnan(h20) or h20 <= 0:
            return False, None
        dd = (px / h20) - 1
        for thresh, risk in dd_tiers:
            if dd >= thresh:
                if risk is None and thresh == dd_tiers[0][0]:
                    return False, None  # full risk
                elif risk is None:
                    return True, None   # blocked
                else:
                    return False, risk
        return True, None  # below all tiers = blocked
    return filt


# ── Run Phase 4 tests ────────────────────────────────────────────────────
print("\n" + "=" * 90)
print("  PHASE 4A: RESCUE FILTERS (reduced risk on dd20d-blocked entries)")
print("=" * 90)

configs = []

# Baseline
configs.append(("v2.8 baseline", baseline_dd20d))

# RSI rescue
for rsi_key in ['rsi_14', 'rsi_7']:
    for thresh in [20, 30, 40]:
        for rescue_risk in [0.15, 0.25, 0.35]:
            configs.append((
                f"rescue RSI({rsi_key[-2:]}) <={thresh} risk={rescue_risk}",
                make_rescue_by_rsi(rsi_key, thresh, rescue_risk)
            ))

# StochRSI rescue
for stoch_key in ['stoch_k_14_14_3', 'stoch_k_11_7_20']:
    for thresh in [10, 20, 30]:
        for rescue_risk in [0.15, 0.25]:
            configs.append((
                f"rescue StochRSI({stoch_key[-7:]}) <={thresh} risk={rescue_risk}",
                make_rescue_by_stoch_rsi(stoch_key, thresh, rescue_risk)
            ))

# Velocity rescue
for vel_key in ['velocity_6', 'velocity_24']:
    for thresh in [-0.01, 0.0, 0.01]:
        for rescue_risk in [0.15, 0.25]:
            configs.append((
                f"rescue vel({vel_key[-2:]}) >={thresh*100:.0f}% risk={rescue_risk}",
                make_rescue_by_velocity(vel_key, thresh, rescue_risk)
            ))

# Span B rescue
for span_key in ['span_b_120', 'span_b_240']:
    for rescue_risk in [0.15, 0.25]:
        configs.append((
            f"rescue SpanB({span_key[-3:]}) risk={rescue_risk}",
            make_rescue_by_span_b(span_key, rescue_risk)
        ))

# ATR ratio rescue
for atr_thresh in [0.8, 1.0, 1.2, 1.5]:
    for rescue_risk in [0.15, 0.25]:
        configs.append((
            f"rescue ATR_ratio <={atr_thresh} risk={rescue_risk}",
            make_rescue_by_atr_ratio(atr_thresh, rescue_risk)
        ))

results = []
for label, filt in configs:
    t0 = time.time()
    r = run_backtest_dynamic(filt, label)
    elapsed = time.time() - t0
    r['time'] = round(elapsed, 1)
    results.append(r)
    liq_str = f" LIQ={r['liq']}" if r['liq'] > 0 else ""
    resc_str = f" rescued={r['rescued']}" if r['rescued'] > 0 else ""
    print(f"  {label:<55} CAGR={r['cagr']:>6.1f}%  MaxDD={r['max_dd']:>5.1f}%  "
          f"Trades={r['trades']:>5}{liq_str}{resc_str}")

# ── Phase 4B: Dynamic risk tiers ─────────────────────────────────────────
print("\n" + "=" * 90)
print("  PHASE 4B: DYNAMIC RISK TIERS")
print("=" * 90)

tier_configs = [
    ("tiered: -10%=0.30, -20%=block", [(-0.10, None), (-0.20, 0.30), (-1.0, None)]),
    ("tiered: -10%=0.25, -20%=block", [(-0.10, None), (-0.20, 0.25), (-1.0, None)]),
    ("tiered: -10%=0.15, -20%=block", [(-0.10, None), (-0.20, 0.15), (-1.0, None)]),
    ("tiered: -10%=0.30, -15%=0.15, -25%=block", [(-0.10, None), (-0.15, 0.30), (-0.25, 0.15), (-1.0, None)]),
    ("tiered: -10%=0.25, -15%=0.15, -25%=block", [(-0.10, None), (-0.15, 0.25), (-0.25, 0.15), (-1.0, None)]),
    ("tiered: -12%=0.30, -20%=block", [(-0.12, None), (-0.20, 0.30), (-1.0, None)]),
    ("tiered: -12%=0.25, -20%=0.10, -30%=block", [(-0.12, None), (-0.20, 0.25), (-0.30, 0.10), (-1.0, None)]),
    ("tiered: -8%=0.35, -15%=0.20, -25%=block", [(-0.08, None), (-0.15, 0.35), (-0.25, 0.20), (-1.0, None)]),
]

results_b = []
for label, tiers in tier_configs:
    filt = make_dynamic_risk_by_dd(tiers)
    t0 = time.time()
    r = run_backtest_dynamic(filt, label)
    elapsed = time.time() - t0
    r['time'] = round(elapsed, 1)
    results_b.append(r)
    liq_str = f" LIQ={r['liq']}" if r['liq'] > 0 else ""
    resc_str = f" rescued={r['rescued']}" if r['rescued'] > 0 else ""
    print(f"  {label:<55} CAGR={r['cagr']:>6.1f}%  MaxDD={r['max_dd']:>5.1f}%  "
          f"Trades={r['trades']:>5}{liq_str}{resc_str}")

all_results = results + results_b

# ── Summary ──────────────────────────────────────────────────────────────
print("\n" + "=" * 90)
print("  PHASE 4 RANKING — 0-LIQ CONFIGS BY CAGR")
print("=" * 90)

zero_liq = sorted([r for r in all_results if r['liq'] == 0],
                   key=lambda x: x['cagr'], reverse=True)

print(f"\n  {'Rank':<5} {'Label':<55} {'CAGR':>7} {'MaxDD':>7} {'Trades':>7} {'Rescued':>8}")
print(f"  {'-'*5} {'-'*55} {'-'*7} {'-'*7} {'-'*7} {'-'*8}")
for i, r in enumerate(zero_liq[:25], 1):
    marker = " <-- v2.8" if r['label'] == "v2.8 baseline" else ""
    print(f"  {i:<5} {r['label']:<55} {r['cagr']:>6.1f}% {r['max_dd']:>6.1f}% "
          f"{r['trades']:>7} {r.get('rescued', 0):>8}{marker}")

out_path = os.path.join(os.path.dirname(__file__), 'v29_phase4_results.json')
with open(out_path, 'w') as f:
    json.dump(all_results, f, indent=2)
print(f"\nPhase 4 results saved to {out_path}")
print("Done.")
