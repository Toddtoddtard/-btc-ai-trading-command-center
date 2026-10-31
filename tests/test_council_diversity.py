import unittest
from council_v4 import council_vote


class CouncilDiversityTests(unittest.TestCase):
    def test_related_trend_votes_do_not_count_as_three_independent_confirmations(self):
        votes = {n: {'score': .8, 'confidence': .8} for n in
                 ('Trend AI', 'Historical Pattern AI', 'Market Regime AI')}
        result = council_vote(votes, {})
        self.assertEqual(result['evidence_families'], 1)
        self.assertEqual(result['consensus_coverage'], 0)
        self.assertEqual(len(result['members']), 3)

    def test_independent_rare_signal_is_retained_and_can_add_corroboration(self):
        votes = {n: {'score': .8, 'confidence': .8} for n in ('Trend AI', 'Whale AI', 'Liquidity AI')}
        result = council_vote(votes, {})
        self.assertEqual(result['evidence_families'], 3)
        self.assertGreater(result['consensus_coverage'], .8)

    def test_changed_confidence_formula_cannot_borrow_legacy_calibration(self):
        from council_confidence import fit
        records=[]
        for i in range(250):
            records.append(({'opened_at':i*100,'expires_at':i*100+10,'snapshot':{
                'master_base_score':.5,'master_confidence':.6,
                **({'confidence_policy':'evidence-families-v1'} if i>=240 else {})}},
                {'kalshi_result':'yes','official_observed_at':i*100+11}))
        model=fit(records,as_of=30000)
        self.assertEqual(model['training_markets'],10)
        self.assertFalse(model['active'])

    def test_active_legacy_calibration_cannot_inflate_new_formula(self):
        votes={n:{'score':.2,'confidence':.7,'reason':'healthy'} for n in ['Trend AI','Whale AI','Liquidity AI']}
        raw=council_vote(votes,{})['confidence']
        legacy={'council_confidence_calibration':{
            'basis':'official_council_confidence_bands_v1','active':True,
            'bands':{str(int(raw*10)):{'samples':100,'residual_sum':15,'validated':True}}}}
        self.assertEqual(council_vote(votes,legacy)['confidence'],raw)
