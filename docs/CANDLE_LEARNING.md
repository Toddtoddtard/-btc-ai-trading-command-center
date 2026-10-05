# Candle education and complete-minute learning

Implemented 2026-10-05. `candle_learning.py` is called by `learner_v31.py`.
The worker retrieves a two-day initial warmup and then resumes at its persisted
closed-minute cursor. Up to four 1,000-row pages per run bound the workload;
older backlog remains queued rather than silently skipped. Each consecutive
closed minute is studied, regardless of WAIT, LOCK, SCALP or whether a trade exists.
A missing or malformed minute blocks progress until it is retrieved successfully.
This is spot-price learning, not official Kalshi settlement training.

## What is learned

Separate online logistic models learn BTC close-to-close direction at 1, 5 and
15 minutes from 22 bounded features: signed body, both wicks, close location,
doji, engulfing, inside bar, excursions beyond prior highs/lows followed by a
close back inside, relative volume/range, 3/15/60-minute returns, wick/trend and
wick/volume interactions, taker imbalance with a missing-data flag, and body/wick
shape on aligned completed 5m and 15m candles. Existing specialists and the
separate 30m/1h/4h/12h/day/week/month context remain active.

Every replay prediction is made from its historical prefix; its saved probability
is scored only when its deadline closes. SGD then updates current weights. Raw
current higher-timeframe or order-book snapshots are never attached to past rows.
A replay score is not a live forecast, trade win rate, or profitability claim.

Fresh predictions captured during actual worker runs have a separate live queue.
Live origins are spaced by at least their forecast horizon to avoid counting
heavily overlapping observations as independent evidence. Promotion requires
200 live outcomes, 500 recent replay outcomes, at least 70% live directional
accuracy, and Brier-score improvement over both 50/50 and a fixed momentum
baseline. Replay samples cannot satisfy the live gate. A qualified 15-minute
model can supply the existing 25% horizon-model component of the shared Python
forecast. Otherwise its influence is zero. Gates are reevaluated each run.
No paper balance, historical trades, entry caps, or official settlements change.

## Internet sources translated into measurable features

- CME Group, Chart Types: body/wick/open/high/low/close and close-location concepts.
  https://www.cmegroup.com/education/courses/technical-analysis/chart-types-candlestick-line-bar
- Binance Spot REST market data: kline open/close timestamps, volume, taker-buy
  volume, 1,000-row pagination, startTime/endTime.
  https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints
- Binance official stream documentation: a forming kline is distinct from a
  completed kline (`x`); closed-minute REST data is used here.
  https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md
- scikit-learn TimeSeriesSplit: temporal ordering and gaps prevent training on
  future observations. This online implementation instead delays each update
  until the actual horizon deadline and separately captures live evidence.
  https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html
- GitHub Actions schedule limitations: cron can be delayed or dropped.
  https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule

Pattern names are feature definitions, not promises of predictive value. Internet
articles are not injected as instructions or fabricated examples. Weight changes
come from observed market outcomes. Catch-up cannot recreate missed live trades,
order books, intrabar tick sequences, or independent live validation samples.
The existing forecast's decorative candle shapes are not learned future OHLC.
