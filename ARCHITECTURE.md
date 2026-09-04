# BTC AI Trading Command Center — Architecture

```text
Binance spot (price, 1m candles, aggregate trades)
                 │
                 ├──────────────┐
                 │              │
Binance futures (depth, funding, OI)
                 │              │
                 └──────┬───────┘
                        │
Kalshi public BTC markets (KXBTC15M / hourly)
                        │
                        ▼
                 Shared AI Core
                    ai_core.py
        ┌───────────────┼────────────────┐
        │               │                │
  indicators      specialist AIs   15m candle path
        │               │                │
        └───────────────┼────────────────┘
                        │
              ┌─────────┴─────────┐
              ▼                   ▼
          Streamlit app       24/7 learner
            app.py             learner.py
              │                   │
              │                   ├─ grade final-price error
              │                   ├─ grade 15-candle path error
              │                   ├─ adapt specialist weights
              │                   └─ check official Kalshi result
              │
              ▼
      Master 15-minute AI
 SCALP UP / SCALP DOWN / LOCK UP /
       LOCK DOWN / HOLD
              │
              ▼
          Risk engine
              │
              ▼
     PAPER-ONLY execution
              │
      prediction journal /
         walk-forward test

24/7 learner ──every 5 min──> learning-state branch
                                 │
                                 ▼
                         Streamlit reads state
```

## Shared-model guarantee

`app.py` and `learner.py` use the same specialist and forecast implementations from `ai_core.py`. This prevents the dashboard from showing one set of formulas while the scheduled learner grades another.

## Specialist council

The shared specialist council contains Trend, Momentum, Volume, Pattern, Support/Resistance, Volatility, Market Regime, Whale, Liquidity, Derivatives, Kalshi Context, Historical Pattern, and Combination AI.

`Kalshi Context AI` is intentionally named this way because its inputs are Kalshi market probability and BTC distance from the active target; it is not a news/event feed.

## Kalshi target handling

The current KXBTC15M contract is chosen deterministically and then re-fetched by exact ticker. The target remains pinned to that contract until expiration. The app, chart, decision engine, and learner use the same target semantics.

The live BTC underlying is a Binance proxy. For learning, final-price/path errors are therefore measured from Binance 1-minute data. Separately, the learner checks the official settled Kalshi market `result` and records YES/NO accuracy when the result becomes available.

## Learning state

GitHub Actions runs `.github/workflows/learn.yml` every five minutes. The worker writes version-2 state to the `learning-state` branch. State includes bounded forecast weights, specialist adaptive weights, rolling history, real 15-candle path error for newly registered windows, and official Kalshi settlement accuracy.

## Safety boundary

The application remains paper trading only. There are no live exchange order endpoints, no private exchange credentials, and no real-money execution path in this architecture.
