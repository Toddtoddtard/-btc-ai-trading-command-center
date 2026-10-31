import copy
import unittest

class ScalpExitResearchTests(unittest.TestCase):
    def observe(self, state, at=1000, bid=.49, ask=.5, ticker='T', action='SCALP UP'):
        from scalp_exit_research import observe
        return observe(state, dict(ticker=ticker, master_action=action, expires_at=1600),
                       dict(ticker=ticker, quotes_observed_at=at, yes_bid_dollars=bid,
                            yes_ask_dollars=ask, execution_book={'available':True,
                              'yes_bid_size':10,'yes_ask_size':10}), now=at)

    def test_entry_is_frozen_and_terminal_probability_never_becomes_exit_forecast(self):
        s={}; self.observe(s)
        r=copy.deepcopy(s['scalp_exit_research']['pending'][0])
        self.observe(s,at=1010,ask=.7,bid=.69)
        after=s['scalp_exit_research']['pending'][0]
        self.assertEqual(r['entry'],after['entry'])
        self.assertEqual(r['target'],after['target'])
        self.assertEqual(r['probability'],after['probability'])
        self.assertGreater(after['target'], .53)  # one-contract fees covered
        self.assertFalse(s['scalp_exit_research']['affects_execution'])

    def test_observed_target_needs_its_own_official_outcome_before_scoring(self):
        from scalp_exit_research import resolve, scorecard
        s={};self.observe(s);self.observe(s,at=1050,bid=.8,ask=.81)
        resolve(s,lambda _: {'ticker':'T','status':'open','result':'yes'},now=1700)
        self.assertEqual(scorecard(s)['eligible_official_markets'],0)
        resolve(s,lambda _: {'ticker':'T','status':'finalized','result':'no'},now=1700)
        card=scorecard(s)
        self.assertEqual(card['eligible_official_markets'],1)
        self.assertEqual(card['target_hits'],1)
        self.assertGreater(card['net_pnl'],0)
        self.assertFalse(card['affects_execution'])

    def test_unobserved_path_is_censored_instead_of_inventing_target_or_stop(self):
        from scalp_exit_research import resolve, scorecard
        s={};self.observe(s)
        resolve(s,lambda _: {'ticker':'T','status':'finalized','result':'yes'},now=1700)
        c=scorecard(s)
        self.assertEqual(c['censored_markets'],1)
        self.assertEqual(c['eligible_official_markets'],0)

    def test_stale_depth_and_new_side_do_not_create_or_rewrite_episode(self):
        from scalp_exit_research import observe
        s={};observe(s,dict(ticker='T',master_action='SCALP UP',expires_at=1600),
                     dict(ticker='T',quotes_observed_at=900,execution_book={'available':True}),now=1000)
        self.assertEqual(s['scalp_exit_research']['pending'],[])
        self.observe(s);self.observe(s,at=1010,action='SCALP DOWN')
        self.assertEqual(len(s['scalp_exit_research']['pending']),1)
        self.assertEqual(s['scalp_exit_research']['pending'][0]['side'],'YES')
