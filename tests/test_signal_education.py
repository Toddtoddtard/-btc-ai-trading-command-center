import unittest
import pandas as pd
from signal_education import detect_signals, summarize_signals
from research_lab import register_shadow, resolve_shadows
from kalshi_paper_engine import kalshi_taker_fee


class SignalEducationTests(unittest.TestCase):
    def bars(self, bullish=True):
        f = pd.DataFrame(dict(time=pd.date_range('2026-01-01', periods=70, freq='min', tz='UTC'),
                              open=100., close=100., high=101., low=99., volume=10.))
        f.loc[68, ['open', 'close']] = [100.5, 99.5] if bullish else [99.5, 100.5]
        f.loc[69, ['open', 'close', 'high', 'low', 'volume']] = (
            [99., 103., 104., 98., 20.] if bullish else [101., 97., 102., 96., 20.])
        return f, f.time.iloc[-1].timestamp() + 60

    def test_both_directions_and_volume_confirmation(self):
        for bullish, prefix, suffix, side in [(True, 'Bullish', 'up', 'YES'), (False, 'Bearish', 'down', 'NO')]:
            f, now = self.bars(bullish)
            signals = {s['name']: s for s in detect_signals(f, now)}
            for name in [prefix + ' engulfing', prefix + ' MACD crossover', 'Volume breakout ' + suffix]:
                self.assertEqual(signals[name]['direction'], side)
            f.loc[69, 'volume'] = 10
            self.assertNotIn('Volume breakout ' + suffix, [s['name'] for s in detect_signals(f, now)])

    def test_no_unfinished_stale_or_gapped_inputs(self):
        f, now = self.bars()
        self.assertNotIn('Bullish engulfing', [s['name'] for s in detect_signals(f, now - 1)])
        self.assertEqual(detect_signals(f, now + 121), [])
        self.assertEqual(detect_signals(f.drop(index=40), now), [])
        self.assertEqual(detect_signals([]), [])

    def observation(self):
        return dict(ticker='A', opened_at=100, expires_at=1000, phase='OPEN', result='yes',
                    master_action='WAIT', yes_ask=.61, no_ask=.41,
                    named_signals=[dict(name='Bullish engulfing', direction='YES',
                                        observed_at=100, candle_closed_at=60, trend='UP')])

    def test_unique_market_official_results_and_fee_adjusted_wait(self):
        row = self.observation()
        later = dict(row, opened_at=800, phase='FINAL 2', yes_ask=.99)
        ungraded = dict(row, ticker='B', result=None)
        result = summarize_signals([later, ungraded, row])
        total = next(r for r in result['ranking'] if r['context'] == 'ALL')
        self.assertEqual((total['samples'], total['wins']), (1, 1))
        self.assertAlmostEqual(total['net_pnl'], 1 - .61 - kalshi_taker_fee(1, .61))
        self.assertFalse(result['affects_execution'])

    def test_invalid_timing_or_quotes_never_score(self):
        for overrides in [dict(observed_at=101), dict(candle_closed_at=101), dict(observed_at=1001)]:
            row = self.observation()
            row['named_signals'][0].update(overrides)
            self.assertEqual(summarize_signals([row])['ranking'], [])
        row = self.observation()
        row['yes_ask'] = float('nan')
        self.assertEqual(summarize_signals([row])['ranking'], [])

    def test_integration_wait_observation_settles_once(self):
        state = {}
        row = self.observation()
        self.assertTrue(register_shadow(state, row, dict(yes_bid=.59, yes_ask=.61, no_ask=.41)))
        resolve_shadows(state, lambda ticker: None)
        self.assertEqual(state['research_lab']['signal_education']['ranking'], [])
        resolve_shadows(state, lambda ticker: 'no')
        resolve_shadows(state, lambda ticker: 'no')
        total = next(r for r in state['research_lab']['signal_education']['ranking'] if r['context'] == 'ALL')
        self.assertEqual((total['samples'], total['wins']), (1, 0))
        self.assertAlmostEqual(total['net_pnl'], -.61 - kalshi_taker_fee(1, .61))
