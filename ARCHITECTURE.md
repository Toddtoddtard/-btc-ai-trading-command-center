                 ┌──────────────────────┐
                 │      BINANCE         │
                 │ spot + futures       │
                 │ candles + trades     │
                 │ depth + funding + OI │
                 └──────────┬───────────┘
                            │
                 ┌──────────▼───────────┐
                 │       AGGR           │
                 │ trade aggregation    │
                 │ flow / large trades  │
                 └──────────┬───────────┘
                            │
                 ┌──────────▼───────────┐
                 │       KALSHI         │
                 │ prediction markets   │
                 │ probability signals  │
                 └──────────┬───────────┘
                            │
                 ┌──────────▼───────────┐
                 │    MARKET DATA HUB   │
                 │ concurrent fetching  │
                 │ stale detection       │
                 │ source health         │
                 └──────────┬───────────┘
                            │
                 ┌──────────▼───────────┐
                 │   FEATURE ENGINE     │
                 │ momentum             │
                 │ volatility           │
                 │ order flow           │
                 │ regime               │
                 │ derivatives          │
                 │ sentiment            │
                 └──────────┬───────────┘
                            │
       ┌────────┬───────────┼───────────┬─────────┐
       ▼        ▼           ▼           ▼         ▼
     Trend   Momentum   Order Flow   Volatility  Regime
       │        │           │           │         │
       └────────┴───────────┼───────────┴─────────┘
                            ▼
                 ┌──────────────────────┐
                 │  INTERACTION ENGINE  │
                 │ specialist agreement │
                 │ disagreement         │
                 │ regime weighting     │
                 └──────────┬───────────┘
                            ▼
                 ┌──────────────────────┐
                 │ MASTER 15-MIN AI     │
                 │ LONG / SHORT / HOLD  │
                 │ probability          │
                 │ expected move        │
                 │ horizon              │
                 └──────────┬───────────┘
                            ▼
                 ┌──────────────────────┐
                 │    RISK ENGINE       │
                 │ position sizing      │
                 │ SL / TP              │
                 │ daily loss           │
                 │ drawdown             │
                 │ stale-data shutdown  │
                 └──────────┬───────────┘
                            ▼
                 ┌──────────────────────┐
                 │    PAPER BROKER      │
                 │ fills                │
                 │ fees                │
                 │ slippage             │
                 │ spread               │
                 │ P&L                  │
                 └──────────┬───────────┘
                            │
                 ┌──────────▼───────────┐
                 │   PREDICTION JOURNAL │
                 │ every prediction     │
                 │ features             │
                 │ outcome              │
                 │ error                │
                 │ P&L                  │
                 └──────────┬───────────┘
                            ▼
                 ┌──────────────────────┐
                 │   WALK-FORWARD TEST  │
                 │ OOS evaluation       │
                 │ fees/slippage        │
                 │ drawdown             │
                 │ Sharpe / Sortino     │
                 │ profit factor        │
                 └──────────┬───────────┘
                            ▼
                 ┌──────────────────────┐
                 │ CONTROLLED LEARNER   │
                 │ specialist scoring   │
                 │ bounded weights      │
                 │ versioned changes    │
                 │ no uncontrolled      │
                 │ self-modification    │
                 └──────────────────────┘