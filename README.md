# BTC AI Trading Command Center

A paper-trading-only Bitcoin and Kalshi prediction dashboard built with Streamlit.

## Current architecture

- `app.py` — Streamlit dashboard, paper account, risk engine, prediction journal, Kalshi views, persistent live chart, backtesting, and UI.
- `dashboard_ui.py` — presentation-only formatters, directional badges, and themed tables.
- `live_feeds.py` — testable concurrent loading of independent Binance and Kalshi reads.
- `ai_core.py` — shared indicator, specialist-AI, and 15-minute forecast-path logic used by both the dashboard and the 24/7 learner.
- `horizon_models.py` — separate leakage-safe 1-, 5-, and 15-minute probability models with prequential grading and strict promotion gates.
- `kalshi_microstructure.py` — reconstructs executable bid/ask, spread, depth imbalance, and microprice from Kalshi's public bid-only order book.
- `learner.py` — scheduled online learner. It grades completed windows, adapts specialist weights, measures final-price and 15-candle path error, and separately tracks official Kalshi YES/NO settlement accuracy.
- `research_lab.py` — paper-only multi-phase shadow calls, Kalshi-baseline Brier scoring, fee-aware policy trials, WAIT counterfactuals, and advisory specialist lifecycle states.
- `.github/workflows/learn.yml` — runs the learner every 5 minutes and publishes `learning_state.json` to the `learning-state` branch.

## Data sources

- Binance spot: BTC price, 1-minute candles, aggregate trades.
- Binance futures: funding, open interest, and depth imbalance.
- Kalshi public read-only API: KXBTC15M and hourly BTC market context/targets.

The BTC chart uses Binance as a real-time market proxy. Kalshi's public order book supplies current executable quote context. Official Kalshi outcome accuracy is tracked from the settled Kalshi market result when available.

The horizon models remain shadow-only until they beat the legacy baseline on an untouched chronological holdout and then repeat that Brier-score edge on at least 200 live, test-then-train observations. A weekly workflow retrains from up to ten years of Binance Vision one-minute archives using 70% train, 15% calibration, and 15% untouched test periods. Promotion never enables real-money execution; the project remains paper-only.

## Specialist AIs

Trend AI, Momentum AI, Volume AI, Pattern AI, Support/Resistance AI, Volatility AI, Market Regime AI, Whale AI, Liquidity AI, Derivatives AI, Kalshi Context AI, Historical Pattern AI, and Combination AI feed the Master AI.

The 15-minute action vocabulary is `SCALP UP`, `SCALP DOWN`, `LOCK UP`, `LOCK DOWN`, or `HOLD`.

## Learning

The dashboard and background learner now import the same `ai_core.py`, preventing formula drift between what the app displays and what the worker grades. The learner records true 15-candle forecast-path error for newly registered windows and retains bounded adaptive specialist weights. Existing pre-upgrade windows are preserved and migrate forward safely.

## Safety

This repository is intentionally **paper trading only**. It contains no exchange private keys and no live-money order execution endpoints.

## Run locally

1. Install Python 3.10+.
2. Run `pip install -r requirements.txt`.
3. Run `streamlit run app.py`.
