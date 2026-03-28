"""
MRM v2.9 — Phase 5: Fine-tune top rescue configs
==================================================
Top 0-liq winners from Phase 4:
  1. RSI(14) <=30 rescue risk=0.25  — 119.1% CAGR, 1505 trades
  2. SpanB(240) rescue risk=0.25    — 103.3% CAGR, 1162 trades
  3. vel(6) >=0% rescue risk=0.25   — 99.4% CAGR, 1122 trades
  4. RSI(14) <=30 rescue risk=0.15  — 105.0% CAGR, 1505 trades

Fine-tune:
  A. Sweep rescue_risk around best values
  B. Sweep main risk_pct
  C. Sweep RSI threshold more finely
  D. Combine rescue indicators
"""
import pandas as pd, numpy as np, time, json, os

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

c4h, c4l, c4c = c4['h'], c4['l'], c4['c']

# RSI
def compute_rsi(closes, period):
    delta = closes.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

# Span B
def compute_span_b(highs, lows, period):
    return (highs.rolling(period).max() + lows.rolling(period).min()) / 2.0

# Velocity
c4['rsi_14'] = compute_rsi(c4c, 14)
c4['rsi_7'] = compute_rsi(c4c, 7)
for p in [120, 180, 240, 300]:
    c4[f'span_b_{p}'] = compute_span_b(c4h, c4l, p)
c4['velocity_6'] = c4c.pct_change(6)

# ATR ratio
def compute_atr(highs, lows, closes, period):
    prev_close = closes.shift(1)
    tr = pd.concat([highs - lows, (highs - prev_close).abs(), (lows - prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()

c4['atr_14'] = compute_atr(c4h, c4l, c4c, 14)
c4['atr_44'] = compute_atr(c4h, c4l, c4c, 44)
c4['atr_ratio'] = c4['atr_14'] / c4['atr_44']

ema_v = c4['ema34'].values
sma_v = c4['sma14'].values
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

NOT_MULTS = [1.0, 2.0, 5.0, 12.5, 87.5]

def cum_drops(gaps):
    result, acc = [], 0.0
    for g in gaps:
        acc += g
        result.append(acc / 100.0)
    return result

def run_bt(filter_fn, label="", risk_pct=0.50):
    p = dict(
        risk_pct=risk_pct, tp_pct=0.005,
        level_gaps=[0.5, 1.5, 10.0, 14.0],
        max_levels=5, long_trigger_pct=0.005, short_trigger_pct=0.08,
        unfav_trigger_scale=3.0, unfav_risk_scale=0.60,
        unfav_spacing_scale=1.60, unfav_hold_scale=0.45,
        max_hold_bars=720, min_equity=50,
        comm=0.00045, taker=0.000432, maker=0.000144,
        fund_8h=0.000013, slip=0.03, maint=0.005,
    )
    balance = 1000.0
    n_tp = n_to = n_liq = 0
    active = False; direction = None; favored = None
    levels = []; drops = []; max_hold = 0; entry_candle = 0
    cooldown_until = 0; peak_equity = 1000.0; max_drawdown = 0.0
    level_dist = {}; long_count = short_count = fav_count = unfav_count = filtered_count = rescued_count = 0
    liq_events = []; monthly = {}

    for i in range(min(n, sim_end_idx + 1)):
        ci = bar_to_candle[i]
        is_boundary = (i == bounds[ci])
        if i >= sim_idx:
            equity = balance
            if active and levels:
                total_qty = sum(lv[3] for lv in levels)
                blended = sum(lv[3] * lv[1] for lv in levels) / total_qty
                equity = balance + total_qty * (c_arr[i] - blended)
            if equity > peak_equity: peak_equity = equity
            dd = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0
            if dd > max_drawdown: max_drawdown = dd
            tp_ = pd.Timestamp(ts_arr[i])
            k = (tp_.year, tp_.month)
            if k not in monthly: monthly[k] = {'s': equity, 'e': equity}
            monthly[k]['e'] = equity

        if active:
            total_qty = sum(lv[3] for lv in levels)
            blended = sum(lv[3] * lv[1] for lv in levels) / total_qty
            total_notional = sum(lv[2] for lv in levels)
            worst_px = l_arr[i] if direction == 'long' else h_arr[i]
            unrealized = total_qty * (worst_px - blended)
            if balance + unrealized <= total_notional * p['maint']:
                n_liq += 1
                liq_events.append(f"{pd.Timestamp(ts_arr[i])} {direction} L{len(levels)}")
                balance = 1000.0; active = False; levels = []
                cooldown_until = ci + 1; peak_equity = 1000.0; continue

            if len(levels) < p['max_levels']:
                for li in range(len(levels), p['max_levels']):
                    if li - 1 >= len(drops): break
                    l1_price = levels[0][1]; drop_pct = drops[li - 1]
                    if direction == 'long':
                        ft = l1_price * (1 - drop_pct); hit = l_arr[i] <= ft
                    else:
                        ft = l1_price * (1 + drop_pct); hit = h_arr[i] >= ft
                    if hit:
                        fp = (ft - p['slip']) if direction == 'long' else (ft + p['slip'])
                        ln = levels[0][2] * NOT_MULTS[li]
                        lq = ln / fp if direction == 'long' else -ln / fp
                        balance -= ln * (p['maker'] + p['comm'])
                        levels.append((li+1, fp, ln, lq, i)); break

            total_qty = sum(lv[3] for lv in levels)
            blended = sum(lv[3] * lv[1] for lv in levels) / total_qty
            total_notional = sum(lv[2] for lv in levels)
            best_px = h_arr[i] if direction == 'long' else l_arr[i]
            tp_price = blended * (1 + p['tp_pct']) if direction == 'long' else blended * (1 - p['tp_pct'])
            tp_hit = best_px >= tp_price if direction == 'long' else best_px <= tp_price

            if tp_hit:
                exit_px = (tp_price - p['slip']) if direction == 'long' else (tp_price + p['slip'])
                fee_out = total_notional * (p['maker'] + p['comm'])
                hm = i - levels[0][4]
                funding = total_notional * p['fund_8h'] * (hm / (8*60))
                pnl = total_qty * (exit_px - blended) - fee_out - funding
                balance += pnl; n_tp += 1; nl = len(levels)
                level_dist[nl] = level_dist.get(nl, 0) + 1
                if direction == 'long': long_count += 1
                else: short_count += 1
                if favored: fav_count += 1
                else: unfav_count += 1
                active = False; levels = []; cooldown_until = ci + 1; continue

            if is_boundary and (ci - entry_candle) >= max_hold:
                exit_px = (c_arr[i] - p['slip']) if direction == 'long' else (c_arr[i] + p['slip'])
                fee_out = total_notional * (p['taker'] + p['comm'])
                hm = i - levels[0][4]
                funding = total_notional * p['fund_8h'] * (hm / (8*60))
                pnl = total_qty * (exit_px - blended) - fee_out - funding
                balance += pnl; n_to += 1; nl = len(levels)
                level_dist[nl] = level_dist.get(nl, 0) + 1
                if direction == 'long': long_count += 1
                else: short_count += 1
                if favored: fav_count += 1
                else: unfav_count += 1
                active = False; levels = []; cooldown_until = ci + 1; continue

        if is_boundary and not active:
            if i < sim_idx or ci < cooldown_until or balance < p['min_equity'] or ci < 1: continue
            prev_candle = ci - 1
            if prev_candle >= len(ema_v): continue
            ema_val = ema_v[prev_candle]; sma_val = sma_v[prev_candle]
            if np.isnan(ema_val) or np.isnan(sma_val): continue
            px = c_arr[i]
            day_ts = np.datetime64(pd.Timestamp(ts_arr[i]).normalize().asm8)
            s440 = sma440_map.get(day_ts)
            if s440 is None or np.isnan(s440):
                s440 = sma440_map.get(day_ts - np.timedelta64(1, 'D'))
            if s440 is None or (isinstance(s440, float) and np.isnan(s440)): continue

            is_bull = px > s440
            pbe = (ema_val - px) / ema_val; pbs = (sma_val - px) / sma_val
            pae = (px - ema_val) / ema_val; pas = (px - sma_val) / sma_val
            entered = False

            lf = is_bull
            trigger = p['long_trigger_pct'] if lf else p['long_trigger_pct'] * p['unfav_trigger_scale']
            risk = p['risk_pct'] if lf else p['risk_pct'] * p['unfav_risk_scale']
            hold = p['max_hold_bars'] if lf else int(p['max_hold_bars'] * p['unfav_hold_scale'])
            gaps = p['level_gaps'] if lf else [g * p['unfav_spacing_scale'] for g in p['level_gaps']]

            if pbe >= trigger and pbs >= trigger:
                skip, risk_override = filter_fn(prev_candle, px, 'long', c4_dict)
                if skip: filtered_count += 1
                else:
                    if risk_override is not None:
                        risk = risk_override if lf else risk_override * p['unfav_risk_scale']
                        rescued_count += 1
                if not skip:
                    ep = px + p['slip']; not_ = risk * balance; qty = not_ / ep
                    balance -= not_ * (p['taker'] + p['comm'])
                    levels = [(1, ep, not_, qty, i)]
                    direction = 'long'; favored = lf; drops = cum_drops(gaps)
                    max_hold = hold; entry_candle = ci; active = True; entered = True

            if not entered:
                sf = not is_bull
                trigger = p['short_trigger_pct'] if sf else p['short_trigger_pct'] * p['unfav_trigger_scale']
                risk = p['risk_pct'] if sf else p['risk_pct'] * p['unfav_risk_scale']
                hold = p['max_hold_bars'] if sf else int(p['max_hold_bars'] * p['unfav_hold_scale'])
                gaps = p['level_gaps'] if sf else [g * p['unfav_spacing_scale'] for g in p['level_gaps']]
                if pae >= trigger and pas >= trigger:
                    ep = px - p['slip']; not_ = risk * balance; qty = -not_ / ep
                    balance -= not_ * (p['taker'] + p['comm'])
                    levels = [(1, ep, not_, qty, i)]
                    direction = 'short'; favored = sf; drops = cum_drops(gaps)
                    max_hold = hold; entry_candle = ci; active = True

    total = n_tp + n_to + n_liq
    yrs = (SIM_END - SIM_START).days / 365.25
    cagr = ((balance / 1000) ** (1 / yrs) - 1) if balance > 0 else -1.0
    sorted_months = sorted(monthly.keys()); n_months = len(sorted_months)
    prod = 1.0
    for ym in sorted_months:
        d = monthly[ym]; r = d['e'] / d['s'] if d['s'] > 0 else 1; prod *= r
    cmr = prod ** (1 / n_months) - 1 if n_months > 0 else 0

    return {
        'label': label, 'cagr': round(cagr*100, 1), 'cmr': round(cmr*100, 2),
        'max_dd': round(max_drawdown*100, 1), 'trades': total,
        'tp': n_tp, 'to': n_to, 'liq': n_liq,
        'longs': long_count, 'shorts': short_count,
        'filtered': filtered_count, 'rescued': rescued_count,
        'final_eq': round(balance, 0),
        'levels': dict(sorted(level_dist.items())),
        'liq_events': liq_events,
    }


def make_rsi_rescue(rsi_key, thresh, rescue_risk):
    def filt(prev_candle, px, direction, c4d):
        if direction != 'long': return False, None
        h20 = c4d['high_20d'][prev_candle] if prev_candle < len(c4d['high_20d']) else np.nan
        if np.isnan(h20) or h20 <= 0: return False, None
        dd = (px / h20) - 1
        if dd >= -0.10: return False, None
        rsi = c4d[rsi_key][prev_candle] if prev_candle < len(c4d[rsi_key]) else np.nan
        if not np.isnan(rsi) and rsi <= thresh: return False, rescue_risk
        return True, None
    return filt

def make_spanb_rescue(period, rescue_risk):
    key = f'span_b_{period}'
    def filt(prev_candle, px, direction, c4d):
        if direction != 'long': return False, None
        h20 = c4d['high_20d'][prev_candle] if prev_candle < len(c4d['high_20d']) else np.nan
        if np.isnan(h20) or h20 <= 0: return False, None
        dd = (px / h20) - 1
        if dd >= -0.10: return False, None
        sb = c4d[key][prev_candle] if prev_candle < len(c4d[key]) else np.nan
        if not np.isnan(sb) and px >= sb: return False, rescue_risk
        return True, None
    return filt

def make_vel_rescue(vel_key, vel_thresh, rescue_risk):
    def filt(prev_candle, px, direction, c4d):
        if direction != 'long': return False, None
        h20 = c4d['high_20d'][prev_candle] if prev_candle < len(c4d['high_20d']) else np.nan
        if np.isnan(h20) or h20 <= 0: return False, None
        dd = (px / h20) - 1
        if dd >= -0.10: return False, None
        vel = c4d[vel_key][prev_candle] if prev_candle < len(c4d[vel_key]) else np.nan
        if not np.isnan(vel) and vel >= vel_thresh: return False, rescue_risk
        return True, None
    return filt

def make_combo_rescue(rsi_key, rsi_thresh, span_key, rescue_risk):
    """Rescue only if BOTH RSI oversold AND above Span B."""
    def filt(prev_candle, px, direction, c4d):
        if direction != 'long': return False, None
        h20 = c4d['high_20d'][prev_candle] if prev_candle < len(c4d['high_20d']) else np.nan
        if np.isnan(h20) or h20 <= 0: return False, None
        dd = (px / h20) - 1
        if dd >= -0.10: return False, None
        rsi = c4d[rsi_key][prev_candle] if prev_candle < len(c4d[rsi_key]) else np.nan
        sb = c4d[span_key][prev_candle] if prev_candle < len(c4d[span_key]) else np.nan
        if not np.isnan(rsi) and rsi <= rsi_thresh and not np.isnan(sb) and px >= sb:
            return False, rescue_risk
        return True, None
    return filt


print(f"Data: {n:,} bars | Sim: {SIM_START.date()} to {SIM_END.date()}")

# ── 5A: Fine-tune RSI(14) rescue threshold & rescue_risk ─────────────────
print("\n" + "=" * 90)
print("  5A: RSI(14) RESCUE — THRESHOLD & RISK SWEEP")
print("=" * 90)

results = []
for thresh in [25, 28, 30, 32, 35]:
    for rescue_risk in [0.18, 0.20, 0.22, 0.25, 0.28, 0.30]:
        label = f"RSI14 <={thresh} rescue={rescue_risk}"
        filt = make_rsi_rescue('rsi_14', thresh, rescue_risk)
        r = run_bt(filt, label, risk_pct=0.50)
        results.append(r)
        liq_str = f" LIQ={r['liq']}" if r['liq'] > 0 else ""
        print(f"  {label:<40} CAGR={r['cagr']:>6.1f}%  MaxDD={r['max_dd']:>5.1f}%  "
              f"Trades={r['trades']:>5}{liq_str}")

# ── 5B: Main risk sweep on best RSI rescue ────────────────────────────────
print("\n" + "=" * 90)
print("  5B: MAIN RISK SWEEP ON RSI(14) <=30 rescue=0.25")
print("=" * 90)

for main_risk in [0.40, 0.46, 0.48, 0.50, 0.52, 0.54]:
    label = f"RSI14<=30 resc=0.25 | mainRisk={main_risk}"
    filt = make_rsi_rescue('rsi_14', 30, 0.25)
    r = run_bt(filt, label, risk_pct=main_risk)
    results.append(r)
    liq_str = f" LIQ={r['liq']}" if r['liq'] > 0 else ""
    print(f"  {label:<50} CAGR={r['cagr']:>6.1f}%  MaxDD={r['max_dd']:>5.1f}%  "
          f"Trades={r['trades']:>5}{liq_str}")

# ── 5C: SpanB period sweep ────────────────────────────────────────────────
print("\n" + "=" * 90)
print("  5C: SPAN B RESCUE — PERIOD & RISK SWEEP")
print("=" * 90)

for period in [180, 240, 300]:
    for rescue_risk in [0.20, 0.25, 0.30]:
        label = f"SpanB({period}) rescue={rescue_risk}"
        filt = make_spanb_rescue(period, rescue_risk)
        r = run_bt(filt, label, risk_pct=0.50)
        results.append(r)
        liq_str = f" LIQ={r['liq']}" if r['liq'] > 0 else ""
        print(f"  {label:<40} CAGR={r['cagr']:>6.1f}%  MaxDD={r['max_dd']:>5.1f}%  "
              f"Trades={r['trades']:>5}{liq_str}")

# ── 5D: Combo: RSI + SpanB dual rescue ────────────────────────────────────
print("\n" + "=" * 90)
print("  5D: COMBO RESCUE (RSI + SpanB)")
print("=" * 90)

for rsi_thresh in [30, 35, 40]:
    for span_p in [180, 240]:
        for rescue_risk in [0.25, 0.30, 0.35]:
            label = f"RSI14<={rsi_thresh} & SpanB({span_p}) resc={rescue_risk}"
            filt = make_combo_rescue('rsi_14', rsi_thresh, f'span_b_{span_p}', rescue_risk)
            r = run_bt(filt, label, risk_pct=0.50)
            results.append(r)
            liq_str = f" LIQ={r['liq']}" if r['liq'] > 0 else ""
            print(f"  {label:<50} CAGR={r['cagr']:>6.1f}%  MaxDD={r['max_dd']:>5.1f}%  "
                  f"Trades={r['trades']:>5}{liq_str}")

# ── 5E: Main risk sweep on best combo ────────────────────────────────────
print("\n" + "=" * 90)
print("  5E: RISK SWEEP ON BEST COMBO")
print("=" * 90)

# Pick best 0-liq from 5D
zero_liq_5d = [r for r in results if r['liq'] == 0 and 'SpanB' in r['label'] and 'RSI' in r['label']]
if zero_liq_5d:
    best_5d = max(zero_liq_5d, key=lambda x: x['cagr'])
    print(f"  Best combo: {best_5d['label']} — {best_5d['cagr']}% CAGR")
    # Extract params from label (hacky but works)
    # Re-run with different main risks
    for main_risk in [0.46, 0.50, 0.52, 0.54]:
        label = f"{best_5d['label']} | mainRisk={main_risk}"
        # Parse: "RSI14<=30 & SpanB(240) resc=0.25"
        # Just reuse the best filter
        parts = best_5d['label']
        rsi_t = int(parts.split('<=')[1].split(' ')[0])
        span_p = int(parts.split('SpanB(')[1].split(')')[0])
        rr = float(parts.split('resc=')[1])
        filt = make_combo_rescue('rsi_14', rsi_t, f'span_b_{span_p}', rr)
        r = run_bt(filt, label, risk_pct=main_risk)
        results.append(r)
        liq_str = f" LIQ={r['liq']}" if r['liq'] > 0 else ""
        print(f"  {label:<55} CAGR={r['cagr']:>6.1f}%  MaxDD={r['max_dd']:>5.1f}%  Trades={r['trades']:>5}{liq_str}")

# ── Final ranking ────────────────────────────────────────────────────────
print("\n" + "=" * 90)
print("  PHASE 5 FINAL RANKING — 0-LIQ BY CAGR")
print("=" * 90)

zero_liq = sorted([r for r in results if r['liq'] == 0], key=lambda x: x['cagr'], reverse=True)
print(f"\n  {'#':<4} {'Label':<55} {'CAGR':>7} {'CMR':>7} {'MaxDD':>7} {'Trades':>7} {'Rescued':>8}")
print(f"  {'-'*4} {'-'*55} {'-'*7} {'-'*7} {'-'*7} {'-'*7} {'-'*8}")
for i, r in enumerate(zero_liq[:30], 1):
    print(f"  {i:<4} {r['label']:<55} {r['cagr']:>6.1f}% {r['cmr']:>6.2f}% "
          f"{r['max_dd']:>6.1f}% {r['trades']:>7} {r.get('rescued',0):>8}")

out = os.path.join(os.path.dirname(__file__), 'v29_phase5_results.json')
with open(out, 'w') as f:
    json.dump(results, f, indent=2)
print(f"\nSaved to {out}")
