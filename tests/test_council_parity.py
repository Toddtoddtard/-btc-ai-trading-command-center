import copy
import unittest
from council_v4 import council_vote, analyze_bot_contributions
from specialist_knowledge_v5 import knowledge_council_vote
from learner_v3 import weighted_master_confidence, update_regime_learning
from council_accounting import reconcile_specialists, BASIS


class CouncilParityTests(unittest.TestCase):
    def test_background_and_dashboard_have_identical_vote(self):
        results={'Trend AI':{'score':.8,'confidence':.7},'Momentum AI':{'score':-.2,'confidence':.6},
                 'Combination AI':{'score':-1,'confidence':.99},'Liquidity AI':{'score':0,'confidence':.9}}
        state={'specialists':{},'status':{'current_regime':'RANGE'}}
        v=knowledge_council_vote(results,state,'RANGE')
        self.assertEqual(weighted_master_confidence({'specialists':results,'regime':'RANGE'},state),(v['confidence'],v['base_score']))
        self.assertEqual({m['name'] for m in v['members']},{'Trend AI','Momentum AI'})
        self.assertAlmostEqual(sum(m['vote_share'] for m in v['members']),1)

    def test_neutral_specialists_do_not_dilute_or_lose(self):
        result={'Trend AI':{'score':.8,'confidence':.8}}
        original=council_vote(result,{})
        result.update({'Liquidity AI':{'score':0,'confidence':.8},'Political Event Watch AI':{'score':.9,'confidence':.9,'event_status':'INACTIVE'}})
        self.assertEqual(original["base_score"],council_vote(result,{})["base_score"])
        self.assertEqual(original["members"],council_vote(result,{})["members"])
        s={'specialists':{'Liquidity AI':{'samples':20}}}
        update_regime_learning(s,{'specialists':{'Liquidity AI':{'score':0}},'regime':'RANGE'},1,.01,1)
        self.assertNotIn('regimes',s['specialists']['Liquidity AI'])

    def evidence(self):
        return {'specialists':{'Trend AI':{'samples':999,'direction_hits':999}},
                'prediction_snapshots':[{'ticker':'A','snapshot':{'regime':'RANGE','specialists':{
                    'Trend AI':{'score':.8,'confidence':.8},'Liquidity AI':{'score':0,'confidence':.8}}}},
                    {'ticker':'unknown','snapshot':{'specialists':{'Trend AI':{'score':1}}}}],
                'master_history':[{'ticker':'A','kalshi_result':'yes','direction_correct':0,'realized_return':-.02}]}

    def test_official_target_wins_even_when_spot_falls_and_no_duplicate(self):
        s=self.evidence();s['prediction_snapshots'].append(copy.deepcopy(s['prediction_snapshots'][0]))
        report=analyze_bot_contributions(s)
        rows={r['name']:r for r in report['ranking']}
        self.assertEqual(report['label_basis'],BASIS)
        self.assertEqual(rows['Trend AI']['standalone_accuracy'],1)
        self.assertEqual(rows['Trend AI']['directional_calls'],1)
        self.assertIsNone(rows['Liquidity AI']['standalone_accuracy'])
        reconcile_specialists(s)
        self.assertEqual(s['specialists']['Trend AI']['samples'],1)
        self.assertEqual(s['specialists']['Trend AI']['direction_hits'],1)
        self.assertEqual(s['specialists']['Liquidity AI']['samples'],0)
        self.assertEqual(s['legacy_specialist_accounting']['specialists']['Trend AI']['samples'],999)
        before=copy.deepcopy(s['specialists']);reconcile_specialists(s)
        self.assertEqual(before,s['specialists'])

    def test_unknown_official_result_does_not_borrow_spot_label(self):
        s=self.evidence();s['master_history'][0].pop('kalshi_result')
        report=analyze_bot_contributions(s)
        self.assertEqual(report['evaluated_snapshots'],0)

    def test_late_snapshot_cannot_be_counted_as_prediction(self):
        s=self.evidence()
        s['prediction_snapshots'][0].update(opened_at=101,expires_at=100)
        reconcile_specialists(s)
        self.assertEqual(s['specialists']['Trend AI']['samples'],0)
        self.assertEqual(analyze_bot_contributions(s)['evaluated_snapshots'],0)

    def test_no_active_calls_cannot_be_declared_harmful(self):
        s=self.evidence()
        report=analyze_bot_contributions(s,min_samples=1)
        row=next(r for r in report['ranking'] if r['name']=='Liquidity AI')
        self.assertEqual(row['verdict'],'LEARNING')
        self.assertEqual(row['directional_calls'],0)
