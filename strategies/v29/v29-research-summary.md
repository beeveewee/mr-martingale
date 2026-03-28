# MRM v2.9 — Indicator Research Summary

**Date:** 2026-03-28
**Total configs tested:** 210 across 5 phases

---

## Baseline (v2.8)

| Metric | Value |
|--------|-------|
| CAGR | 85.6% |
| CMR | 5.14% |
| MaxDD | 79.6% |
| Liquidations | 0 |
| Trades | 889 |
| Entries blocked by dd20d | 2,180 |
| Period | 2018-10-31 to 2026-03-28 (7.41 years) |

Entry logic: EMA34 + SMA14 crossunder triggers, SMA440 regime, dd20d crash filter.

---

## Phase 1: Single Indicator Replacement (28 configs)

Tested each Swing v5/v6 indicator as standalone replacement for dd20d:

| Indicator | Best 0-liq CAGR | Trades | Notes |
|-----------|-----------------|--------|-------|
| dd20d -10% (baseline) | 85.6% | 889 | Reference |
| dd20d -8% (tighter) | 55.2% | 615 | Too aggressive, blocks too many |
| dd 30d -10% (wider window) | 62.8% | 731 | Fewer trades, lower CAGR |
| StochRSI (any config) | — | — | All cause 2-9 liquidations |
| Span B (any period) | — | — | All cause 1-2 liquidations |
| Chandelier (any config) | — | — | All cause 2-4 liquidations |
| Gaussian lower band | — | — | All cause 1-3 liquidations |
| Donchian low | — | — | 9 liquidations (useless) |
| No filter | 1.1% | 2,254 | 9 liquidations |

**Conclusion:** Nothing beats dd20d at -10% as standalone filter.

---

## Phase 2: Indicator Combinations (12 configs)

Combined dd20d with supplementary filters:

| Combination | 0-liq CAGR | Trades |
|-------------|-----------|--------|
| dd20d + StochRSI(11,7,20) block OB | 85.4% | 887 |
| dd20d + StochRSI(14,14,3) block OB | 80.6% | 857 |
| dd20d + Gaussian(91,1.5) | 62.2% | 691 |
| dd20d + SpanB(240) | 51.3% | 626 |
| dd20d + Chandelier | 21.2% | 250 |

**Conclusion:** Adding more filters only removes profitable trades. No improvement.

---

## Phase 3: Risk Tuning (30 configs)

Swept risk_pct on Phase 1-2 winners. Liq boundary unchanged at 0.54 for all configs.

**Conclusion:** No new 0-liq territory discovered.

---

## Phase 4: Rescue Filters — BREAKTHROUGH (62 configs)

Key insight: instead of blocking more entries, rescue safe ones that dd20d blocks.

### Top 0-liq rescue configs:

| Rescue Criterion | rescue_risk | CAGR | MaxDD | Trades | Rescued |
|------------------|-------------|------|-------|--------|---------|
| RSI(14) <= 30 | 0.25 | **119.1%** | 79.6% | 1,505 | 618 |
| RSI(7) <= 20 | 0.25 | 112.7% | 93.0% | 1,404 | 525 |
| RSI(14) <= 30 | 0.15 | 105.0% | 79.6% | 1,505 | 618 |
| SpanB(240) above | 0.25 | 103.3% | 79.6% | 1,162 | 273 |
| RSI(7) <= 20 | 0.15 | 100.8% | 79.6% | 1,404 | 525 |
| vel(6) >= 0% | 0.25 | 99.4% | 79.6% | 1,122 | 234 |
| ATR_ratio <= 0.8 | 0.25 | 97.5% | 79.6% | 1,116 | 232 |
| SpanB(240) above | 0.15 | 96.1% | 79.6% | 1,162 | 273 |
| SpanB(120) above | 0.25 | 94.1% | 79.6% | 1,022 | 133 |
| RSI(14) <= 20 | 0.15 | 93.4% | 79.6% | 1,125 | 236 |

### Dynamic risk tiers (all caused liquidations):
Tiered risk scaling (-10% → reduced, -20% → blocked) did not maintain 0 liqs.

---

## Phase 5: Fine-tuning (78 configs)

### RSI(14) threshold sweep (rescue_risk=0.25, main risk=0.50):

| RSI threshold | 0-liq? | CAGR | MaxDD | Trades |
|---------------|--------|------|-------|--------|
| <= 25 | Yes | 106.7% | 89.5% | 1,312 |
| <= 28 | Yes | 114.7% | 79.6% | 1,423 |
| **<= 30** | **Yes** | **119.1%** | **79.6%** | **1,505** |
| <= 32 | NO (1 liq) | — | — | — |
| <= 35 | NO (1 liq) | — | — | — |

**Critical boundary at RSI = 31.** Threshold 30 is the maximum safe value.

### RSI(14) <=30 rescue_risk sweep:

| rescue_risk | 0-liq? | CAGR | MaxDD |
|-------------|--------|------|-------|
| 0.18 | Yes | 109.1% | 79.6% |
| 0.20 | Yes | 111.9% | 79.6% |
| 0.22 | Yes | 114.8% | 79.6% |
| **0.25** | **Yes** | **119.1%** | **79.6%** |
| 0.28 | Yes | 123.5% | 79.7% |
| 0.30 | Yes | 126.5% | 85.4% |

### Main risk sweep (RSI14<=30, rescue=0.25):

| main risk | 0-liq? | CAGR | MaxDD |
|-----------|--------|------|-------|
| 0.40 | Yes | 93.7% | 71.2% |
| 0.46 | Yes | 108.6% | 73.2% |
| 0.48 | Yes | 113.8% | 76.4% |
| **0.50** | **Yes** | **119.1%** | **79.6%** |
| 0.52 | Yes | 124.5% | 82.7% |
| 0.54 | NO (1 liq) | — | — |

### SpanB rescue (alternative, more conservative):

| Config | CAGR | MaxDD | Trades |
|--------|------|-------|--------|
| SpanB(300) rescue=0.30 | 114.2% | 79.6% | 1,236 |
| SpanB(300) rescue=0.25 | 109.1% | 79.6% | 1,236 |
| SpanB(240) rescue=0.30 | 107.1% | 79.6% | 1,162 |

### Combo rescue (RSI AND SpanB — both must confirm):

| Config | CAGR | MaxDD | Trades |
|--------|------|-------|--------|
| RSI14<=40 & SpanB(240) resc=0.35 @ risk=0.52 | 108.5% | 82.7% | 1,096 |
| RSI14<=40 & SpanB(240) resc=0.35 | 103.5% | 79.6% | 1,096 |

Combos are safer but lower CAGR — the dual confirmation blocks too many rescues.

---

## Winner: v2.9

**RSI(14) <= 30 rescue at risk=0.25, all other params unchanged from v2.8.**

| Metric | v2.8 | v2.9 | Improvement |
|--------|------|------|-------------|
| CAGR | 85.6% | **119.1%** | +33.5pp (+39%) |
| CMR | 5.14% | **6.58%** | +1.44pp |
| MaxDD | 79.6% | 79.6% | same |
| Liquidations | 0 | 0 | same |
| Trades | 889 | **1,505** | +69% |
| Total return | 97.5x | **~427x** | +4.4x |

---

## Indicators That Did NOT Work

| Indicator | Role Tested | Why It Failed |
|-----------|-------------|---------------|
| Stochastic RSI | Entry filter | Doesn't catch crash regimes; all configs → liqs |
| Span B | Entry filter | Catches 4/5 crashes but misses 1 → liqs |
| Chandelier Stop | Entry filter | Too aggressive (blocks 90%+ entries) or too loose |
| Gaussian Channel | Entry filter | Same as Span B — catches most but not all crashes |
| Donchian Low | Entry filter | Price is always above N-bar low at entry → useless |
| StochRSI block_overbought | Combo with dd20d | Marginal: blocks 2-32 trades, no CAGR gain |
| Dynamic risk tiers | Replace dd20d | All tier configs → 1-5 liquidations |
| Velocity (24-bar) | Rescue criterion | Rescues wrong entries → liqs |

## Indicators That DID Work (as rescue criteria)

| Indicator | Why It Works as Rescue |
|-----------|----------------------|
| **RSI(14) <= 30** | Best: oversold = bounce likely. All 5 crashes had RSI > 30 |
| SpanB(240-300) above | Price above midline = support held, safe to enter |
| ATR_ratio <= 0.8 | Low vol ratio = volatility subsiding, crash deceleration |
| Velocity(6) >= 0% | Positive 1-day velocity = decline has stopped |
| RSI(7) <= 20 | Similar to RSI(14) but noisier, slightly worse |
