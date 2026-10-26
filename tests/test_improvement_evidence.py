import copy
import importlib
import unittest
import tempfile
import json
from pathlib import Path

import settlement_predictor as predictor
from tests.test_settlement_predictor import EXPIRY, TICKER, market, feed


class ImprovementEvidenceTests(unittest.TestCase):
    def module(self):
        from pathlib import Path
        self.assertTrue(Path('improvement_evidence.py').exists(), 'Paired prospective evidence is missing')
        return importlib.import_module('improvement_evidence')

    def row(self, i, current=.8, previous=.3, market=.4, result='yes'):
        module = self.module()
        opened = EXPIRY-600+i*900
        prediction = predictor.predict(globals()['market'](), feed(EXPIRY-600), {}, now=EXPIRY-600)
        prediction.update(ticker='T'+str(i), captured_at=opened, expires_at=opened+600,
                          probability_yes=current, base_probability_yes=current,
                          market_probability_yes=market)
        return dict(ticker='T'+str(i), opened_at=opened, expires_at=opened+600,
            result=result, result_observed_at=opened+620, settlement_prediction=prediction,
            trial_version=module.VERSION, code_revision='revision-a',
            comparison_probabilities=dict(production=current, previous_execution=previous,
                                          market=market, independent=current))

    def test_paired_gain_requires_same_market_and_observed_official_result(self):
        module = self.module()
        history = [self.row(i) for i in range(110)]
        state = {'settlement_predictor': {'history': history+copy.deepcopy(history)}}
        report = module.scorecard(state, as_of=EXPIRY+110*900)
        paired = report['by_horizon']['10m']['previous_execution']
        self.assertEqual(paired['samples'], 110)
        self.assertAlmostEqual(paired['accuracy'], 1.)
        self.assertGreater(paired['brier_gain_low'], 0)
        self.assertTrue(paired['target_70_verified'])
        self.assertEqual(module.scorecard(state, as_of=EXPIRY-1)['overall']['market']['samples'], 0)

    def test_no_historical_backfill_and_no_unpaired_comparison(self):
        module = self.module()
        a, b = self.row(0), self.row(1)
        a.pop('trial_version')
        b['comparison_probabilities'].pop('previous_execution')
        report = module.scorecard({'settlement_predictor': {'history': [a,b]}}, as_of=EXPIRY+2000)
        self.assertEqual(report['overall']['previous_execution']['samples'], 0)
        self.assertEqual(report['overall']['market']['samples'], 1)

    def test_equal_or_worse_results_cannot_be_reported_as_improvement(self):
        module = self.module()
        state = {'settlement_predictor': {'history': [self.row(i,current=.4,previous=.8)
                                                        for i in range(110)]}}
        result = module.scorecard(state, as_of=EXPIRY+110*900)['overall']['previous_execution']
        self.assertEqual(result['status'], 'NOT_IMPROVED')
        self.assertLess(result['brier_gain'], 0)

    def test_capture_freezes_production_baselines_and_revision(self):
        module = self.module()
        now = EXPIRY-600
        call = dict(ticker=TICKER, opened_at=now, expires_at=EXPIRY,
            contract_probability_up=.7, previous_contract_probability_up=.6,
            code_revision='revision-a', settlement_prediction=predictor.predict(market(),feed(now),{},now=now))
        state = {}
        predictor.record_observation(state, call, market())
        frozen = copy.deepcopy(state['settlement_predictor']['pending'][0])
        call['contract_probability_up'] = .99
        self.assertEqual(frozen['trial_version'], module.VERSION)
        self.assertEqual(frozen['comparison_probabilities']['production'], .7)
        self.assertEqual(frozen['comparison_probabilities']['previous_execution'], .6)
        self.assertEqual(frozen['code_revision'], 'revision-a')

    def test_headline_matches_production_instead_of_unqualified_raw_model(self):
        module = self.module()
        prediction = dict(available=True,ticker=TICKER,probability_yes=.9,outcome='YES')
        decision = dict(kalshi_ticker=TICKER,contract_probability_up=.2,
                        contract_probability_source='market_midpoint')
        displayed = module.display_forecast(prediction,decision)
        self.assertEqual(displayed['outcome'],'NO')
        self.assertEqual(displayed['probability_yes'],.2)
        self.assertEqual(prediction['probability_yes'],.9)

    def test_actual_profit_excludes_historical_and_open_trades(self):
        module = self.module()
        state = {'status':dict(code_revision='revision-a',prediction_policy_version=module.VERSION),
            'background_paper': {'trades': [
            dict(status='CLOSED',pnl=100),
            dict(status='OPEN',pnl=100,forecast_trial_version=module.VERSION),
            dict(status='CLOSED',pnl=2.,forecast_trial_version=module.VERSION,code_revision='revision-a',closed_at=EXPIRY-1),
            dict(status='CLOSED',pnl=-1.,forecast_trial_version=module.VERSION,code_revision='revision-a',closed_at=EXPIRY-1)]}}
        actual = module.scorecard(state,as_of=EXPIRY)['paper']
        self.assertEqual(actual['closed_trades'],2)
        self.assertEqual(actual['net_pnl'],1.)

    def test_previous_execution_probability_is_frozen_before_new_selector(self):
        from contract_calibration import apply
        view = dict(probability_up=.9,market_probability_up=.4)
        old = apply(view,{})
        self.assertEqual(old.get('previous_probability_up'),.4)

    def test_new_revision_cannot_borrow_old_revision_wins_or_profit(self):
        module = self.module()
        history = [self.row(i) for i in range(110)]
        latest = self.row(110,current=.4,previous=.8)
        latest['code_revision'] = 'revision-b'
        unknown = self.row(111)
        unknown.pop('code_revision')
        state = dict(settlement_predictor=dict(history=history+[latest,unknown]),
            background_paper=dict(trades=[
                dict(status='CLOSED',pnl=100,forecast_trial_version=module.VERSION,code_revision='revision-a',closed_at=EXPIRY),
                dict(status='CLOSED',pnl=-1,forecast_trial_version=module.VERSION,code_revision='revision-b',closed_at=EXPIRY)]))
        report = module.scorecard(state,as_of=EXPIRY+120*900)
        self.assertEqual(report['code_revision'],'revision-b')
        self.assertEqual(report['overall']['previous_execution']['samples'],1)
        self.assertEqual(report['overall']['previous_execution']['status'],'COLLECTING')
        self.assertEqual(report['paper']['net_pnl'],-1)

    def test_published_evidence_preserves_ledger_and_training_history(self):
        module = self.module()
        self.assertTrue(hasattr(module,'publish_summary'))
        state = dict(forecast={'samples':10},background_paper={'cash':500,'trades':[]})
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'state.json'
            path.write_text(json.dumps(state))
            module.publish_summary(path,as_of=EXPIRY)
            saved=json.loads(path.read_text())
        saved.pop('improvement_evidence')
        self.assertEqual(saved,state)
