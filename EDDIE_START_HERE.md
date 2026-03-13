# Eddie Start Here

If you're feeding this repo to another AI, start with **this file first**.

---

## What this repo is

This is a **shareable export** of the Mr. Martingale strategy code and docs.

### Current canonical strategy
- **Canonical research winner:** `v3.0`
- See:
  - `MR_MARTINGALE_V3_STRATEGY.md`
  - `MR_MARTINGALE_V3_SPEC.md`
  - `MR_MARTINGALE_VERSION_HISTORY.md`

### Important naming quirk
The current **v3.0 paper bot** still lives in the **`v2/` folder**.
That is not a mistake.

So:
- `v2/` = current **paper-trading runtime branch**, aligned to **v3.0 parameters**
- `execution/` = old **v1 live-family code**

If you want the current researched paper bot, use **`v2/`**, not `execution/`.

---

## Recommended reading order

1. `EDDIE_START_HERE.md`
2. `MR_MARTINGALE_V3_STRATEGY.md`
3. `MR_MARTINGALE_V3_SPEC.md`
4. `MR_MARTINGALE_VERSION_HISTORY.md`
5. `v2/README.md`
6. `v2/config.py`
7. `v2/paper_bot.py`
8. `signals/` and `tools/` for backtest / optimization work

---

## What v3.0 currently is

### Core design
- true compounding
- no stop-loss
- 5 levels
- 440d SMA soft-bias regime filter
- risk per entry = 25% of current equity
- level gaps = `[0.5, 1.5, 9.0, 6.0]`
- multipliers = `[2.0, 2.5, 2.5, 7.0]`
- short trigger = `1.5%`
- long trigger = `0.5%`
- max hold = `160` bars
- leverage = `20x long / 15x short`

### Canonical headline backtest numbers on record
- CAGR: **~194.4% optimized peak**
- avg compounded monthly ROE: **~9.42%**
- liquidations: **0**
- max drawdown: **~34.8%**

Use the strategy/spec/version-history docs for the exact wording and lineage.

---

## Local setup

### 1) Clone the repo
```bash
git clone https://github.com/beeveewee/mr-martingale.git
cd mr-martingale
```

### 2) Create a Python environment
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
```

### 3) Install the likely required packages
There is no locked requirements file in this export, so install the basics manually.

### Minimum for paper bot + most backtest code
```bash
pip install pandas requests python-dotenv
```

### If you also want the old live-family code / Hyperliquid client pieces available
```bash
pip install eth-account hyperliquid-python-sdk streamlit
```

If a script fails on import, install the missing package ad hoc.

---

## Secrets / env setup

### Good news
For the **current v3 paper bot in `v2/`**, you do **not** need trading keys just to run it in paper mode.
It uses Hyperliquid **public market data**.

### Optional
If you want Discord notifications, add your own Discord webhook.

### Easiest path
The provided launch script expects this file:
```bash
~/.openclaw/ws-731228/.secrets/hyperliquid.env
```

So the lowest-friction way to run the repo unchanged is:
```bash
mkdir -p ~/.openclaw/ws-731228/.secrets
nano ~/.openclaw/ws-731228/.secrets/hyperliquid.env
```

### Minimal env file for paper mode
```bash
DISCORD_WEBHOOK=https://discord.com/api/webhooks/your/webhook
EXTRA_WEBHOOKS=[]
```

If you do not want notifications, you can leave `DISCORD_WEBHOOK` blank or skip the file entirely.

### If you later want to use the old `execution/` live-family code
That code expects additional secrets such as:
```bash
HL_PRIVATE_KEY=...
HL_MAIN_ADDRESS=...
DISCORD_WEBHOOK=...
EXTRA_WEBHOOKS=[]
```

But that is **not required** for the current v3 paper bot.

### Alternative to using the hardcoded secrets path
If you dislike the `~/.openclaw/ws-731228/.secrets/` path, your AI can patch:
- `v2/config.py`
- `v2/scripts/run_v2_paper.sh`

so they load env vars from a local `.env` file instead.

---

## Running the current v3-aligned paper bot

### Dry run
```bash
bash v2/scripts/run_v2_paper.sh --dry-run
```

### Foreground
```bash
bash v2/scripts/run_v2_paper.sh --fg
```

### Background
```bash
bash v2/scripts/run_v2_paper.sh
```

### Logs and state
```bash
tail -f v2/logs/v2_paper_bot.log
cat v2/state/v2_paper_state.json
```

---

## What to change first if you are testing on your side

### Best first experiments
1. **1-minute truth testing**
   - keep strategy logic fixed
   - validate wick/sequence realism more strictly than 5m
2. **FX adaptation work**
   - EURUSD first
   - AUDNZD second
   - adjust for spread + session behavior + venue-specific leverage
3. **Other crypto pairs**
   - ETH
   - XRP
   - SOL
   - then HYPE / BNB / LINK / AVAX
4. **Parameter neighborhood sweeps** around the current winner
   - risk around `23%–25%`
   - short trigger around `1.25%–1.75%`
   - max hold around `128–192` bars
   - nearby spacing and multiplier variants
5. **Walk-forward / rolling out-of-sample** validation

### Metrics to prioritize
Do **not** optimize on CAGR alone.
Track at least:
- CAGR
- compounded monthly ROE
- max drawdown
- Calmar ratio
- liquidation count
- timeout count
- out-of-sample degradation

---

## Repo map

### Current strategy docs
- `MR_MARTINGALE_V3_STRATEGY.md`
- `MR_MARTINGALE_V3_SPEC.md`
- `MR_MARTINGALE_VERSION_HISTORY.md`

### Current paper bot
- `v2/config.py`
- `v2/paper_bot.py`
- `v2/data_fetch.py`
- `v2/notifier.py`
- `v2/scripts/run_v2_paper.sh`

### Old live-family implementation
- `execution/`

### Backtesting / optimization / research
- `signals/`
- `tools/`
- `multi_asset/`
- `DEV_PIPELINE.md`

---

## Important cautions

- The flashy early `v2.0` / first-pass `v2.1` numbers were later **invalidated** by stricter liquidation modeling.
- The current v3.0 branch is the one considered **canonical** because it survived the tighter exact-liq standard.
- This repo export intentionally excludes secrets, runtime state, large caches, and bulky result artifacts.
- If your AI says “the repo is missing some large data files,” that is expected.
- Recreate datasets locally or plug in your own market data.

---

## If you are feeding this to your AI

Give your AI this exact brief:

> Use `MR_MARTINGALE_V3_STRATEGY.md`, `MR_MARTINGALE_V3_SPEC.md`, `MR_MARTINGALE_VERSION_HISTORY.md`, and `v2/config.py` as the ground truth for the current canonical strategy. Treat `v2/` as the active v3.0-aligned paper runtime. Do not assume the older 320%+ CAGR branches are valid unless you can reproduce them under the same exact-liq validation standard.

---

## Fast sanity check

If everything is wired correctly, a dry run should:
- fetch BTC data from Hyperliquid
- compute the 440d regime
- print the current state without placing any real trades

If that works, your local setup is basically alive.
