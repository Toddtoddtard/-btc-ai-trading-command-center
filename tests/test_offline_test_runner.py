import unittest
from tools import run_offline_tests


class OfflineRunnerTests(unittest.TestCase):
    def test_function_style_regressions_are_included(self):
        suite = run_offline_tests.discover_offline_suite()
        def ids(group):
            for item in group:
                if isinstance(item, unittest.TestSuite):
                    yield from ids(item)
                else:
                    yield item.id()
        names = set(ids(suite))
        self.assertIn('test_load_live_feeds_starts_independent_reads_concurrently', names)
        self.assertIn('test_market_page_files_exist', names)
