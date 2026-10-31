import copy
import unittest

class SettlementBenchmarkTests(unittest.TestCase):
    def state(self,n=360):
        rows=[]
        for i in range(n):
            opened=i*1000+1
            rows.append(dict(ticker=str(i),opened_at=opened,expires_at=opened+700,
              result='yes' if i%3 else 'no',result_observed_at=opened+710,
              settlement_prediction=dict(available=True,version='kalshi-final-minute-average-v1',
                 ticker=str(i),captured_at=opened,expires_at=opened+700,
                 quotes_observed_at=opened,reference_timestamp=opened,
                 market_probability_yes=.6,base_probability_yes=.7,
                 probability_yes=.7,features=[1,-.1,.02,0])))
        return {'settlement_predictor':{'history':rows},'research_lab':{'history':[]}}

    def test_holdout_labels_cannot_select_a_different_algorithm(self):
        from settlement_benchmark import benchmark
        s=self.state();a=benchmark(s,as_of=1e9)
        for r in s['settlement_predictor']['history'][-100:]:
            r['result']='no'
        b=benchmark(s,as_of=1e9)
        self.assertEqual(a['selected_on_development_only'],b['selected_on_development_only'])
        self.assertEqual(a['development_mean_gain'],b['development_mean_gain'])
        self.assertNotEqual(a['by_horizon']['10m+']['holdout'],b['by_horizon']['10m+']['holdout'])
        self.assertFalse(a['affects_execution'])

    def test_only_fresh_matching_official_observations_count_once(self):
        from settlement_benchmark import collect_observations
        s=self.state(5);s['research_lab']['history']=copy.deepcopy(s['settlement_predictor']['history'])
        self.assertEqual(len(collect_observations(s,1e9)),5)
        s['research_lab']['history']=[]
        rows=s['settlement_predictor']['history']
        rows[0]['settlement_prediction']['ticker']='OTHER'
        rows[1]['result_observed_at']=1e10
        rows[2]['settlement_prediction']['quotes_observed_at']-=31
        rows[3]['settlement_prediction']['base_probability_yes']=float('nan')
        self.assertEqual(len(collect_observations(s,1e9)),1)

    def test_insufficient_cohorts_do_not_select_or_promote(self):
        from settlement_benchmark import benchmark
        r=benchmark(self.state(100),as_of=1e9)
        self.assertIsNone(r['selected_on_development_only'])
        self.assertFalse(r['affects_execution'])

    def test_same_contract_cannot_be_development_in_one_horizon_and_holdout_in_another(self):
        from settlement_benchmark import benchmark
        s=self.state()
        for r in list(s['settlement_predictor']['history'])[:-3]:
            other=copy.deepcopy(r);other['opened_at']+=350
            other['settlement_prediction'].update(captured_at=other['opened_at'],quotes_observed_at=other['opened_at'],reference_timestamp=other['opened_at'])
            s['settlement_predictor']['history'].append(other)
        report=benchmark(s,as_of=1e9)
        self.assertEqual(report['by_horizon']['5m+']['holdout']['shape']['samples'],97)
        self.assertEqual(report['by_horizon']['10m+']['holdout']['shape']['samples'],100)
