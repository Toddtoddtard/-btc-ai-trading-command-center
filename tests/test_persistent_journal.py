import copy
import json
import unittest

from prediction_journal import ensure_journal, journal_view, record_prediction, resolve_journal


class PersistentJournalTests(unittest.TestCase):
    def setUp(self):
        self.state = {}
        self.market = {"ticker": "BTC-1", "expires_at": 900, "target": 100}

    def record(self, action, now=100):
        return record_prediction(self.state, {"master_action": action}, self.market, now)

    def test_restart_deduplicates_and_first_lock_cannot_reverse(self):
        self.assertTrue(self.record("WAIT"))
        self.assertFalse(self.record("WAIT", 120))
        self.assertTrue(self.record("SCALP UP", 130))
        self.assertFalse(self.record("SCALP DOWN", 140))
        self.assertTrue(self.record("LOCK DOWN", 150))
        self.state = json.loads(json.dumps(self.state))
        self.assertFalse(self.record("LOCK UP", 160))
        self.assertFalse(self.record("WAIT", 170))
        rows, stats = journal_view(self.state)
        self.assertEqual(stats["n"], 1)
        self.assertEqual(rows[0]["action"], "LOCK DOWN")
        self.assertEqual(self.state["prediction_journal"]["rows"][0]["opened_at"], 150)

    def test_official_results_only_and_wait_excluded(self):
        self.record("LOCK UP")
        self.assertEqual(resolve_journal(self.state, lambda _: None, now=1000), 0)
        self.assertEqual(journal_view(self.state)[1]["trade_resolved"], 0)
        self.assertEqual(resolve_journal(self.state, lambda _: "no", now=1100), 1)
        self.market["ticker"] = "BTC-2"
        self.record("WAIT")
        resolve_journal(self.state, lambda _: "yes", now=1200)
        stats = journal_view(self.state)[1]
        self.assertEqual(stats, {"n": 2, "trade_resolved": 1, "wait_resolved": 1, "accuracy": 0.0})
        self.assertEqual(resolve_journal(self.state, lambda _: "yes", now=1300), 0)

    def test_backfill_never_invents_signals_or_spot_settlement(self):
        self.state = {
            "master_history": [
                {"ticker": "BTC-1", "expires_at": 900, "predicted_settlement_direction": 1,
                 "kalshi_result": "yes", "direction_correct": 1},
                {"ticker": "BTC-2", "expires_at": 1800, "direction_correct": 1},
            ],
            "prediction_snapshots": [{"ticker": "BTC-1", "opened_at": 100, "expires_at": 900,
                                       "snapshot": {"start_price": 99, "target": 100}}],
        }
        before = copy.deepcopy(self.state)
        rows, stats = journal_view(self.state)
        self.assertEqual(self.state, before)  # UI is read only
        self.assertEqual(stats["n"], 2)
        self.assertEqual(stats["trade_resolved"], 0)
        self.assertIsNone(stats["accuracy"])
        by_ticker = {r["ticker"]: r for r in rows}
        self.assertEqual(by_ticker["BTC-1"]["resolved"], 1)
        self.assertEqual(by_ticker["BTC-1"]["action"], "FORECAST UP")
        self.assertIsNone(by_ticker["BTC-1"]["correct"])
        self.assertEqual(by_ticker["BTC-2"]["resolved"], 0)
        ensure_journal(self.state)
        self.state["master_history"] = []
        self.state["prediction_snapshots"] = []
        self.assertEqual(journal_view(self.state)[1]["n"], 2)

    def test_offline_ui_uses_same_rows_and_totals_as_worker(self):
        for i in range(160):
            self.market["ticker"] = f"BTC-{i}"
            self.record("LOCK UP")
        resolve_journal(self.state, lambda _: "yes", now=1000, max_requests=200)
        restored = json.loads(json.dumps(self.state))
        rows, stats = journal_view(restored)
        self.assertEqual(len(rows), 160)
        self.assertEqual(stats["n"], 160)
        self.assertEqual(stats["trade_resolved"], 160)
        self.assertEqual(stats["accuracy"], 1)

    def test_no_backdated_or_missing_call_records(self):
        self.assertFalse(self.record("LOCK UP", 900))
        self.assertFalse(record_prediction(self.state, None, self.market, 100))
        self.assertEqual(journal_view(self.state)[1]["n"], 0)

    def test_result_retry_budget_does_not_starve_later_markets(self):
        for i in range(3):
            self.market["ticker"] = f"BTC-{i}"
            self.record("WAIT")
        checked = []
        def fetch(ticker):
            checked.append(ticker)
            raise OSError("offline")
        for now in (1000, 1100, 1200):
            resolve_journal(self.state, fetch, now=now, max_requests=1)
        self.assertEqual(checked, ["BTC-0", "BTC-1", "BTC-2"])

    def test_existing_official_history_resolves_without_network(self):
        self.record("LOCK DOWN")
        self.state["master_history"] = [{"ticker": "BTC-1", "kalshi_result": "no"}]
        def no_network(_):
            self.fail("already settled market should not be fetched")
        resolve_journal(self.state, no_network, now=1000)
        self.assertEqual(journal_view(self.state)[1]["accuracy"], 1)


if __name__ == "__main__":
    unittest.main()
