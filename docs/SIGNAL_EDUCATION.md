# Named signal education

The learner detects named signals on completed one-minute candles. It records
the observation before contract expiry and grades it using the existing official
Kalshi settlement reader. WAIT observations are included. There is no execution
or policy promotion path in this module.

Sources reviewed October 10, 2026:

- Fidelity MACD guide: https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/macd
- StockCharts candlestick education: https://chartschool.stockcharts.com/table-of-contents/chart-analysis/candlestick-charts/introduction-to-candlesticks
- Schwab volume education: https://www.schwab.com/learn/story/trading-volume-as-market-indicator

Implemented hypotheses: bullish/bearish body engulfing, 12/26/9 MACD signal
crossovers, and closes beyond the prior 20-bar range with >=1.5x prior average
volume. The 20-bar/1.5x thresholds are experimental implementation choices, not
source-proven probabilities. A 15-minute trend tag and window phase allow
context comparisons. An invalidation price is recorded as descriptive evidence;
it is not an order or an exit instruction.

Added October 18, 2026: bullish/bearish liquidity sweeps share the candle
learner's existing definition. The last completed candle must trade strictly
beyond the preceding 20 candles' low/high, then close strictly back above/below
that boundary. Merely touching the boundary or closing beyond it is not a
rejected sweep. A bar breaching and reclaiming both sides is ambiguous and
does not emit a directional named sweep. Evidence includes the breached level,
the completed close, and the excursion extreme as descriptive invalidation.
These are chart hypotheses, not proof of hidden stop orders or manipulation.

Pattern AI now recognizes the same setups and learns its aggregate reliability
from official outcomes. Its model version changes to 3, so older Pattern scores
cannot be presented as performance of the changed model. The separate candle
learner retains its unchanged 22-feature schema and learned weights. The named
scorecard measures whether a bullish sweep predicts YES or a bearish sweep NO
at the actual contract strike, rather than crediting any temporary bounce.

Upward price pressure does not necessarily imply settlement above Kalshi's
strike. This experiment explicitly tests that mapping and may find it poor.
No percentage confidence is invented from a pattern name. Fee-adjusted results
use one hypothetical contract at the recorded side ask. They are counterfactual
settlement P/L, not executed trades, and do not model slippage or early exits.

Only the earliest eligible occurrence per signal per ticker counts, across all
phases. Statistics use the retained 1,000 research observations and can shrink
as that history rolls. No historical signal labels are fabricated. Stale feeds,
gaps, unfinished candles, and missing executable side asks are excluded.
GitHub scheduling gaps still limit live observations. Existing candle replay
learning remains separate and continues recovering closed minutes.

This is a first signal catalog, not coverage of the entire internet. Additional
sources require explicit causal definitions and prospective validation. Any
future trading use must satisfy the existing official-sample, paired-P/L,
drawdown, and repeated-evaluation promotion requirements.
