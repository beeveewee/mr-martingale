"""
MRM v3.0 — Configurable Backtest Engine
=========================================
Simulation loop identical to backtest_v28.py except:
  - entry_fn(ind, px, prev_candle, is_bull) replaces EMA34/SMA14 entry gate
  - regime_fn(ind, px, prev_candle, sma440_val) replaces px > SMA440
  - dd20d and RSI rescue are optional config flags

Grid logic, exit logic, cost model, 1m liq checks: UNCHANGED.
"""
import numpy as np, pandas as pd


def cum_drops(gaps):
    result, acc = [], 0.0
    for g in gaps:
        acc += g
        result.append(acc / 100.0)
    return result


DEFAULT_CONFIG = dict(
    risk_pct=0.50,
    rescue_risk_pct=0.25,
    tp_pct=0.005,
    level_gaps=[0.5, 1.5, 10.0, 14.0],
    level_mults_seq=[2.0, 2.5, 2.5, 7.0],
    max_levels=5,
    short_trigger_pct=0.08,
    unfav_trigger_scale=3.0,
    unfav_risk_scale=0.60,
    unfav_spacing_scale=1.60,
    unfav_hold_scale=0.45,
    max_hold_bars=720,
    min_equity=50,
    # Safety filters
    use_dd20d=True,
    dd20d_threshold=-0.10,
    use_rsi_rescue=True,
    rsi_rescue_thresh=30,
    # Cost model
    comm=0.00045,
    taker=0.000432,
    maker=0.000144,
    fund_8h=0.000013,
    slip=0.03,
    maint=0.005,
)

SIM_START = pd.Timestamp('2018-10-31', tz='UTC')
SIM_END = pd.Timestamp('2026-03-28 23:59:59', tz='UTC')


def run_backtest(data, entry_fn, regime_fn, config=None, label=""):
    """
    Run full backtest with custom entry and regime functions.

    entry_fn(ind, px, prev_candle, is_bull) -> bool
        Returns True if a long entry should be triggered.
        This REPLACES the EMA34/SMA14 crossunder condition.

    regime_fn(ind, px, prev_candle, sma440_val) -> bool
        Returns True if bull regime (favored for longs).
        Receives sma440_val for configs that still want to use it.

    config: dict overriding DEFAULT_CONFIG values.
    """
    p = {**DEFAULT_CONFIG}
    if config:
        p.update(config)

    # Precompute notional multipliers
    not_mults = [1.0]
    _m = 1.0
    for x in p['level_mults_seq']:
        _m *= x
        not_mults.append(_m)

    # Unpack data
    ind = data['ind']
    sma440_map = data['sma440_map']
    ts_arr, h_arr, l_arr, c_arr = data['ts_arr'], data['h_arr'], data['l_arr'], data['c_arr']
    bounds, bar_to_candle = data['bounds'], data['bar_to_candle']
    n = data['n']

    sim_idx = np.searchsorted(ts_arr, np.datetime64(SIM_START.asm8))
    sim_end_idx = np.searchsorted(ts_arr, np.datetime64(SIM_END.asm8))

    # RSI for rescue (preload) — uses close-based RSI to match v2.9
    rsi_vals = ind.get('rsi_close_14')

    # State
    balance = 1000.0
    n_tp = n_to = n_liq = 0
    active = False
    direction = None
    favored = None
    levels = []      # list of (level, price, notional, qty, idx)
    drops = []
    max_hold = 0
    entry_candle = 0
    cooldown_until = 0
    peak_equity = 1000.0
    max_drawdown = 0.0
    level_dist = {}
    long_count = short_count = fav_count = unfav_count = 0
    filtered_count = rescued_count = 0
    liq_events = []
    monthly = {}

    for i in range(min(n, sim_end_idx + 1)):
        ci = bar_to_candle[i]
        is_boundary = (i == bounds[ci])

        # ── Equity tracking ───────────────────────────────────────────
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

        # ── Active position management ────────────────────────────────
        if active:
            total_qty = sum(lv[3] for lv in levels)
            blended = sum(lv[3] * lv[1] for lv in levels) / total_qty
            total_notional = sum(lv[2] for lv in levels)

            # Liquidation check on 1m worst-case wick
            worst_px = l_arr[i] if direction == 'long' else h_arr[i]
            unrealized = total_qty * (worst_px - blended)
            if balance + unrealized <= total_notional * p['maint']:
                n_liq += 1
                liq_events.append(
                    f"{pd.Timestamp(ts_arr[i])} {direction} L{len(levels)} eq=${balance:,.0f}")
                balance = 1000.0
                active = False
                levels = []
                cooldown_until = ci + 1
                peak_equity = 1000.0
                continue

            # Grid fills on 1m bars
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
                        lv_notional = levels[0][2] * not_mults[li]
                        lv_qty = lv_notional / fill_px if direction == 'long' else -lv_notional / fill_px
                        fee_in = lv_notional * (p['maker'] + p['comm'])
                        balance -= fee_in
                        levels.append((li + 1, fill_px, lv_notional, lv_qty, i))
                        break

            # Recompute after potential fill
            total_qty = sum(lv[3] for lv in levels)
            blended = sum(lv[3] * lv[1] for lv in levels) / total_qty
            total_notional = sum(lv[2] for lv in levels)

            # Take-profit on 1m bars
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

            # Timeout on 4H boundary
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

        # ── Entry logic (4H boundary only) ────────────────────────────
        if is_boundary and not active:
            if i < sim_idx or ci < cooldown_until or balance < p['min_equity'] or ci < 1:
                continue
            prev_candle = ci - 1
            if prev_candle >= len(ind['ema34']):
                continue

            px = c_arr[i]

            # Regime determination (custom)
            day_ts = np.datetime64(pd.Timestamp(ts_arr[i]).normalize().asm8)
            s440 = sma440_map.get(day_ts)
            if s440 is None or (isinstance(s440, float) and np.isnan(s440)):
                s440 = sma440_map.get(day_ts - np.timedelta64(1, 'D'))
            if s440 is None or (isinstance(s440, float) and np.isnan(s440)):
                s440 = np.nan

            # If s440 unavailable after lookup attempts, skip entry entirely
            # (matches original v2.8 behavior: continue when s440 is None/NaN)
            if s440 is None or (isinstance(s440, float) and np.isnan(s440)):
                continue

            is_bull = regime_fn(ind, px, prev_candle, s440)

            entered = False

            # ── LONG entry (custom entry_fn replaces EMA34/SMA14 gate) ──
            long_favored = is_bull
            risk = p['risk_pct'] if long_favored else p['risk_pct'] * p['unfav_risk_scale']
            hold = p['max_hold_bars'] if long_favored else int(p['max_hold_bars'] * p['unfav_hold_scale'])
            gaps = p['level_gaps'] if long_favored else [g * p['unfav_spacing_scale'] for g in p['level_gaps']]

            if entry_fn(ind, px, prev_candle, is_bull):
                # dd20d filter (optional)
                use_rescue_risk = False
                skip = False
                if p['use_dd20d']:
                    h20 = ind['high_20d'][prev_candle] if prev_candle < len(ind['high_20d']) else np.nan
                    if not np.isnan(h20) and h20 > 0:
                        dd_from_high = (px / h20) - 1
                        if dd_from_high < p['dd20d_threshold']:
                            # dd20d would block — check RSI rescue
                            if p['use_rsi_rescue'] and rsi_vals is not None:
                                rsi_val = rsi_vals[prev_candle] if prev_candle < len(rsi_vals) else np.nan
                                if not np.isnan(rsi_val) and rsi_val <= p['rsi_rescue_thresh']:
                                    use_rescue_risk = True
                                    rescued_count += 1
                                else:
                                    skip = True
                                    filtered_count += 1
                            else:
                                skip = True
                                filtered_count += 1

                if not skip:
                    if use_rescue_risk:
                        entry_risk = p['rescue_risk_pct'] if long_favored else p['rescue_risk_pct'] * p['unfav_risk_scale']
                    else:
                        entry_risk = risk
                    entry_px = px + p['slip']
                    notional = entry_risk * balance
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

            # ── SHORT entry (unchanged — still uses EMA34/SMA14) ─────
            if not entered:
                ema_val = ind['ema34'][prev_candle]
                sma_val = ind['sma14'][prev_candle]
                if not (np.isnan(ema_val) or np.isnan(sma_val)):
                    short_favored = not is_bull
                    trigger = p['short_trigger_pct'] if short_favored else p['short_trigger_pct'] * p['unfav_trigger_scale']
                    s_risk = p['risk_pct'] if short_favored else p['risk_pct'] * p['unfav_risk_scale']
                    s_hold = p['max_hold_bars'] if short_favored else int(p['max_hold_bars'] * p['unfav_hold_scale'])
                    s_gaps = p['level_gaps'] if short_favored else [g * p['unfav_spacing_scale'] for g in p['level_gaps']]

                    pct_above_ema = (px - ema_val) / ema_val
                    pct_above_sma = (px - sma_val) / sma_val

                    if pct_above_ema >= trigger and pct_above_sma >= trigger:
                        entry_px = px - p['slip']
                        notional = s_risk * balance
                        qty = -notional / entry_px
                        fee_in = notional * (p['taker'] + p['comm'])
                        balance -= fee_in
                        levels = [(1, entry_px, notional, qty, i)]
                        direction = 'short'
                        favored = short_favored
                        drops = cum_drops(s_gaps)
                        max_hold = s_hold
                        entry_candle = ci
                        active = True

    # ── Compute stats ─────────────────────────────────────────────────
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
        'trades': total, 'tp': n_tp, 'to': n_to, 'liq': n_liq,
        'longs': long_count, 'shorts': short_count,
        'fav': fav_count, 'unfav': unfav_count,
        'filtered': filtered_count, 'rescued': rescued_count,
        'final_eq': round(balance, 0),
        'total_return': round(balance / 1000, 1),
        'levels': dict(sorted(level_dist.items())),
        'liq_events': liq_events,
    }
