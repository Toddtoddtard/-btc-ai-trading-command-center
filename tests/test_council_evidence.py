import copy
import unittest
from unittest.mock import patch

from council_v4 import council_vote, analyze_bot_contributions, specialist_active, _contribution_multiplier
from contribution_evidence import paired_evidence, stable_update
from outcome_timing import outcome_available_at
from contract_calibration import observations


class CouncilEvidenceTests(unittest.TestCase):
    def test_one_voter_cannot_earn_unanimous_corroboration_bonus(self):
        vote = council_vote({'Trend AI': {'score': .09, 'confidence': .8}})
        self.assertEqual(vote['consensus'], 1.)
        self.assertEqual(vote['consensus_coverage'], 0.)
        self.assertAlmostEqual(vote['raw_confidence'], .46+.09*.34)
        self.assertEqual(vote['action'], 'WAIT')
        populated = council_vote({n: {'score': .5, 'confidence': .8}
                                  for n in ['Trend AI', 'Momentum AI', 'Volume AI', 'Pattern AI']})
        self.assertEqual(populated['consensus_coverage'], 1.)

    def test_inactive_rare_bot_does_not_dilute_coverage(self):
        results = {'Trend AI': {'score': .5, 'confidence': .8}}
        before = council_vote(results)
        results['Political Event Watch AI'] = {'score': .9, 'event_status': 'INACTIVE'}
        self.assertEqual(before, council_vote(results))
        self.assertTrue(specialist_active('Political Event Watch AI', {'score': .5, 'event_status': 'active'}))
        self.assertTrue(specialist_active('Cross-Market Research AI', {'score': .5, 'research_status': 'active'}))

    def test_exclusion_removes_source_health_effect(self):
        results = {n: {'score': .5, 'confidence': .8, 'reason': 'healthy'}
                   for n in ['Whale AI', 'Liquidity AI', 'Derivatives AI', 'Kalshi Context AI']}
        results['Liquidity AI']['reason'] = 'unavailable'
        self.assertAlmostEqual(council_vote(results)['source_health'], .9)
        self.assertEqual(council_vote(results, exclude={'Liquidity AI'})['source_health'], 1.)

    def test_recorded_poll_time_and_legacy_lag_prevent_boundary_leakage(self):
        self.assertEqual(outcome_available_at({}, 900), 1020)
        self.assertEqual(outcome_available_at({'official_observed_at': 1500}, 900), 1500)
        self.assertEqual(outcome_available_at({'official_observed_at': 940}, 900), 940)
        self.assertEqual(outcome_available_at({'official_observed_at': 'bad'}, 900), float('inf'))
        row = {'ticker': 'A', 'opened_at': 0, 'expires_at': 900, 'result': 'yes',
               'result_observed_at': 1500, 'market_yes_probability': .5, 'contract_probability_up': .6}
        self.assertEqual(observations([row])[0]['available_at'], 1500)

    def test_noise_and_multiple_comparisons_cannot_trigger_weights(self):
        self.assertFalse(paired_evidence(55, 45, 100, 14)['evidence_passed'])
        self.assertFalse(paired_evidence(9, 0, 100, 14)['evidence_passed'])
        self.assertFalse(paired_evidence(10, 0, 99, 14)['evidence_passed'])
        self.assertTrue(paired_evidence(10, 0, 100, 14)['evidence_passed'])

    def test_same_checkpoint_cannot_advance_stability(self):
        row = {'candidate_verdict': 'HIGH VALUE', 'evidence_passed': True, 'contribution_score': .1}
        previous = None
        for _ in range(10):
            previous = {**row, **stable_update(row, previous, 'A')}
        self.assertEqual(previous['evidence_streak'], 1)
        self.assertEqual(previous['stable_multiplier'], 1.)
        for key in ['B', 'C']:
            previous = {**row, **stable_update(row, previous, key)}
        self.assertEqual(previous['evidence_streak'], 3)
        self.assertGreater(previous['stable_multiplier'], 1.)
        self.assertLessEqual(previous['stable_multiplier'], 1.05)
        self.assertEqual(stable_update(dict(row, evidence_passed=False), previous, 'D')['stable_multiplier'], 1.)

    def evidence(self, count=1):
        return {'prediction_snapshots': [{'ticker': str(i), 'opened_at': i*900+10,
                  'expires_at': (i+1)*900, 'snapshot': {'specialists': {
                      'Trend AI': {'score': .09, 'confidence': .8},
                      'Political Event Watch AI': {'score': .5, 'event_status': 'INACTIVE'}}}}
                  for i in range(count)],
                'master_history': [{'ticker': str(i), 'kalshi_result': 'yes'} for i in range(count)]}

    def test_wait_is_excluded_from_accuracy_and_rare_abstention_is_not_redundant(self):
        rows = {r['name']: r for r in analyze_bot_contributions(self.evidence())['ranking']}
        self.assertIsNone(rows['Trend AI']['full_council_accuracy'])
        self.assertEqual(rows['Trend AI']['full_council_calls'], 0)
        self.assertEqual(rows['Trend AI']['unique_saves'], 0)
        self.assertEqual(rows['Political Event Watch AI']['active_samples'], 0)
        self.assertEqual(rows['Political Event Watch AI']['verdict'], 'LEARNING')

    def test_weak_vote_adjusted_into_abstention_is_not_a_loss(self):
        state = self.evidence()
        state['prediction_snapshots'][0]['snapshot']['specialists']['Trend AI']['score'] = .04
        def adjusted(results, learned, regime):
            results = copy.deepcopy(results)
            results['Trend AI']['score'] = .02
            return results, {}
        with patch('specialist_knowledge_v5.knowledge_adjust_results', side_effect=adjusted):
            row = next(r for r in analyze_bot_contributions(state)['ranking'] if r['name'] == 'Trend AI')
        self.assertEqual(row['active_samples'], 0)
        self.assertIsNone(row['standalone_accuracy'])

    def test_helpful_abstention_is_evidence_without_a_fictitious_win(self):
        state = self.evidence()
        def vote(results, learned, regime, exclude=None):
            return {'action': 'SCALP DOWN' if exclude else 'WAIT', 'source_health': 1.}
        with patch('council_v4.council_vote', side_effect=vote):
            report = analyze_bot_contributions(state)
        row = next(r for r in report['ranking'] if r['name'] == 'Trend AI')
        self.assertEqual(row['beneficial_decisions'], 1)
        self.assertEqual(row['abstention_changes'], 1)
        self.assertEqual(row['unique_saves'], 0)
        self.assertEqual(row['full_council_calls'], 0)
        self.assertIsNone(row['full_council_accuracy'])
        self.assertFalse(report['actual_master_execution_replayed'])

    def test_replay_cannot_use_unobserved_previous_settlement(self):
        state = self.evidence(2)
        state['master_history'][0]['official_observed_at'] = 1600
        with patch('council_accounting.reconcile_specialists') as rebuilding:
            analyze_bot_contributions(state)
        self.assertEqual(rebuilding.call_args_list[1].args[0]['prediction_snapshots'], [])

    def test_legacy_or_unstable_rankings_cannot_change_weights(self):
        row = {'name': 'Trend AI', 'stable_multiplier': 1.2, 'evidence_passed': True, 'evidence_streak': 2}
        state = {'bot_intelligence_v4': {'label_basis': 'official_kalshi_directional_calls_v1',
                 'evaluation_mode': 'causal_prior_only_ablation', 'evidence_version': 2, 'ranking': [row]}}
        self.assertEqual(_contribution_multiplier(state, 'Trend AI'), 1.)
        row['evidence_streak'] = 3
        self.assertEqual(_contribution_multiplier(state, 'Trend AI'), 1.2)
        state['bot_intelligence_v4']['evidence_version'] = 1
        self.assertEqual(_contribution_multiplier(state, 'Trend AI'), 1.)
