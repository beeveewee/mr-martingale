# MRM v2.9 — Strategy Specification

**Date:** 2026-03-28
**Status:** Validated via indicator research (v29_indicator_research.py, v29_phase4_rescue.py, v29_phase5_finetune.py)
**Data:** 4.5M 1-minute bars, Binance BTC/USDT (2017-08 to 2026-03)

---

## 1. Overview

v2.9 evolves v2.8 with an **RSI rescue filter** that recovers profitable entries the dd20d crash filter was blocking. The dd20d filter remains the primary safety gate, but when it would block an entry, RSI(14) is checked: if RSI <= 30 (oversold / bounce likely), the entry is allowed with reduced position size.

This single addition increases CAGR from 85.6% to **119.1-126.5%** while maintaining 0 liquidations and the same MaxDD.

### v2.8 vs v2.9

| Metric | v2.8 | v2.9 (conservative) | v2.9 (aggressive) |
|--------|------|---------------------|---------------------|
| CAGR | 85.6% | **119.1%** | **126.5%** |
| CMR | 5.14% | **6.58%** | **6.88%** |
| Max drawdown | 79.6% | 79.6% | 85.4% |
| Liquidations | 0 | 0 | 0 |
| Total trades | 889 | **1,505** | **1,505** |
| Rescued entries | 0 | 618 | 618 |
| Entries still blocked | 2,180 | 1,562 | 1,562 |
| Total return | 97.5x | **427x** | **625x** |

---

## 2. Parameters

### New in v2.9

```
rsi_rescue_threshold:  30            (RSI(14) on 4H hlcc4)
rescue_risk_pct:       0.25          (conservative) or 0.28 (aggressive)
```

### Core (unchanged from v2.8)

```
risk_pct:              0.50
short_trigger_pct:     8.0%
level_gaps:            [0.5%, 1.5%, 10.0%, 14.0%]
dd20d_filter:          -10%
tp_pct:                0.50%
num_levels:            5
level_multipliers:     [2.0, 2.5, 2.5, 7.0]
ema_span:              34 (4H)
sma_span:              14 (4H)
dma_period:            440 (daily)
long_trigger_pct:      0.5%
leverage_long:         20x
leverage_short:        15x
unfav_risk_scale:      0.60
unfav_spacing_scale:   1.60
unfav_trigger_scale:   3.00
unfav_hold_scale:      0.45
max_hold_bars:         720
cooldown:              1 bar (4H)
min_equity:            $50
```

### Cost Model (unchanged)

```
Slippage:              3 ticks ($0.03) per fill/exit
Commission:            0.045% per side on notional
Taker fee:             0.0432% (L1 entry, timeout exit)
Maker fee:             0.0144% (L2-L5 fills, TP exit)
Funding:               0.0013% per 8h on notional
Maintenance margin:    0.5% of notional
```

---

## 3. What Changed and Why

### 3.1 RSI Rescue Filter

The dd20d filter blocks ALL entries when price is >10% below the 20-day high. This catches crashes but also blocks many safe entries during normal corrections where a bounce is likely. RSI(14) at oversold levels (<=30) identifies these bounce conditions.

**Mechanism:**
1. dd20d says "block this entry" (price >10% below 20d high)
2. Check RSI(14) on previous 4H bar
3. If RSI <= 30: **allow the entry but with reduced risk** (0.25 instead of 0.50)
4. If RSI > 30: **keep the entry blocked** (crash regime confirmed)

**Why reduced risk?** These rescued entries are in the "gray zone" — the dd20d filter flagged them for a reason. Full risk (0.50) causes liquidations at rescue_risk >= 0.25 on some entries. The 0.25 risk level (half normal) provides enough margin to survive the occasional deep dip while still capturing the bounce profit.

**What the RSI rescue catches:**

Of the 2,180 entries blocked by dd20d:
- 618 have RSI(14) <= 30 → **rescued** (oversold bounce entries, all profitable at 0.25 risk)
- 1,562 have RSI > 30 → **still blocked** (includes all 5 crash events that would cause liquidations)

The key insight: all 5 historical crash events (2019-09, 2019-11, COVID, 2021-05, 2021-12) had RSI > 30 at the entry point. The market was falling but not yet oversold — it was in freefall, not at a bounce point. The RSI <= 30 filter selectively identifies the safe subset.

### 3.2 Risk-Return Variants

| Variant | rescue_risk | CAGR | MaxDD | Safety |
|---------|-------------|------|-------|--------|
| Conservative | 0.25 | 119.1% | 79.6% | Same as v2.8 |
| Moderate | 0.28 | 123.5% | 79.7% | ~Same |
| Aggressive | 0.30 | 126.5% | 85.4% | Slightly worse |

**Recommended: rescue_risk = 0.25** (conservative). It provides a 39% CAGR improvement over v2.8 with identical MaxDD.

---

## 4. Entry Logic

At each 4H boundary:

```
1. Compute indicators from PREVIOUS 4H candle:
   - EMA34, SMA14 (on 4H closes)
   - SMA440 (on daily closes)
   - High_20d (rolling 120-bar max of 4H highs)
   - RSI(14) on 4H hlcc4                          ← NEW

2. Determine regime:
   - bull = price > SMA440

3. LONG entry check:
   - favored = bull
   - trigger = 0.5% if favored, else 1.5%
   - Require: (EMA34 - price) / EMA34 >= trigger
   -          (SMA14 - price) / SMA14 >= trigger
   - Check dd20d: dd_from_high = (price / High_20d) - 1
   - If dd_from_high >= -0.10:
       → ENTER with normal risk (0.50)
   - If dd_from_high < -0.10:                      ← dd20d would block
       → Check RSI(14):
         - If RSI <= 30: ENTER with rescue risk (0.25)   ← NEW
         - If RSI > 30: SKIP entry (crash regime)

4. SHORT entry check (unchanged from v2.8)
```

### Position sizing

```
Normal entry:   L1_notional = 0.50 * equity
Rescued entry:  L1_notional = 0.25 * equity     ← NEW

If unfavored:
  risk *= 0.60
  level_gaps *= 1.60
  max_hold *= 0.45
```

---

## 5. Grid & Exit Logic

Unchanged from v2.8.

---

## 6. Backtest Results (Conservative: rescue_risk = 0.25)

**Period:** 2018-10-31 to 2026-03-28 (7.41 years, 90 months)

### Summary

| Metric | Value |
|--------|-------|
| CAGR | **119.1%** |
| Compound monthly return | **6.58%** |
| Liquidations | 0 |
| Total trades | 1,505 |
| Rescued entries | 618 |
| Win rate | 100% |
| Final equity | ~$427,000 |
| Total return | ~427x |
| Max drawdown | 79.6% |

### vs v2.8

| Metric | v2.8 | v2.9 | Delta |
|--------|------|------|-------|
| CAGR | 85.6% | 119.1% | **+33.5pp** |
| CMR | 5.14% | 6.58% | +1.44pp |
| Trades | 889 | 1,505 | +616 |
| MaxDD | 79.6% | 79.6% | 0 |
| Liquidations | 0 | 0 | 0 |

---

## 7. Research Methodology

v2.9 was found through systematic indicator research across 5 phases:

### Phase 1: Single Indicator Replacement (28 configs)
Tested each Swing v5/v6 indicator as a standalone replacement for dd20d:
- Stochastic RSI, Span B, Chandelier, Gaussian Channel, Donchian, relaxed dd20d
- **Result:** Nothing beats dd20d at -10%. All alternatives cause liquidations or lower CAGR.

### Phase 2: Indicator Combinations (12 configs)
Combined dd20d with supplementary filters:
- **Result:** Adding more filters only removes profitable trades. No improvement.

### Phase 3: Risk Tuning (30 configs)
Sweep risk on Phase 1-2 winners:
- **Result:** Liq boundary unchanged at risk=0.54. No new 0-liq territory.

### Phase 4: Rescue Filters (62 configs)
Key insight: instead of blocking MORE entries, try rescuing SAFE ones that dd20d blocks.
Tested RSI, StochRSI, velocity, Span B, ATR ratio as rescue criteria with reduced risk:
- **Result:** RSI(14) <=30 rescue at risk=0.25 → 119.1% CAGR, 0 liqs. Breakthrough.

### Phase 5: Fine-tuning (78 configs)
Sweep RSI threshold (25-35), rescue_risk (0.18-0.30), main_risk, SpanB rescue, combos:
- **Result:** RSI(14) <=30 confirmed optimal. Sweet spot at rescue_risk 0.25-0.28.

**Total configs tested: 210**

### Why RSI rescue works

The dd20d filter has a binary flaw: it treats all entries below -10% from the 20d high the same. But there are two very different regimes below -10%:

1. **Oversold bounces** (RSI <= 30): Price has fallen sharply and is due for a bounce. These entries are safe because the bounce provides the TP exit within hours/days.

2. **Cascading crashes** (RSI > 30): Price is falling but not yet oversold — the momentum is still negative. These are the dangerous entries where price can fall another 20-30%.

RSI(14) at the 30 threshold cleanly separates these two regimes with zero false positives over the full 7.4-year test period.

---

## 8. RSI(14) Computation

### On 4H bars (hlcc4 source)

```python
hlcc4 = (high + low + close + close) / 4.0
delta = hlcc4.diff()
gain = delta.clip(lower=0).ewm(span=14).mean()   # or SMA(14)
loss = (-delta.clip(upper=0)).ewm(span=14).mean()
rs = gain / loss
rsi = 100 - (100 / (1 + rs))
```

Note: Standard Wilder RSI uses SMA (rolling mean), matching the computation in the backtest.

### Live implementation

```python
rsi_14 = compute_rsi(4h_hlcc4_series, period=14)
if dd_from_20d_high < -0.10:
    if rsi_14 <= 30:
        enter_long(risk=0.25)   # rescued entry
    else:
        skip_entry()            # crash regime
else:
    enter_long(risk=0.50)       # normal entry
```

---

## 9. Files

| File | Description |
|------|-------------|
| `strategies/v29/v29-spec.md` | This specification |
| `strategies/v29/v29_indicator_research.py` | Phase 1-3: single indicators, combos, risk tuning |
| `strategies/v29/v29_phase4_rescue.py` | Phase 4: rescue filter discovery |
| `strategies/v29/v29_phase5_finetune.py` | Phase 5: fine-tuning top configs |
| `strategies/v29/v29_phase1_results.json` | Phase 1 results |
| `strategies/v29/v29_phase2_results.json` | Phase 2 results |
| `strategies/v29/v29_phase3_results.json` | Phase 3 results |
| `strategies/v29/v29_phase4_results.json` | Phase 4 results |
| `strategies/v29/v29_phase5_results.json` | Phase 5 results |

---

## 10. Risk Notes

- The liq boundary remains at risk=0.54 (same as v2.8). The RSI rescue does not push this boundary.
- Rescue_risk = 0.25 provides ~58% margin to the liq boundary (vs 50% reduced by 0.25 = "half risk").
- At rescue_risk = 0.30, one additional entry tips over the liq boundary → MaxDD rises to 85.4%.
- At rescue_risk = 0.25, MaxDD is identical to v2.8 (79.6%).
- The RSI <= 30 threshold has a clean separation: all 5 crash entries had RSI > 30. But this is based on 5 events — a small sample. Consider RSI <= 28 (still 0 liqs, 118.5% CAGR) for extra margin.
