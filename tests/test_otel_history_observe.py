import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('history_observe', ROOT / 'scripts/otel-history-observe.py')
OBSERVE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OBSERVE)


class HistoryObserverTests(unittest.TestCase):
    def test_only_pinned_binary_in_its_process_group_is_counted(self):
        snapshot = '\n'.join(['1 10 20 /private/job/otel-history export --source private',
                              '2 11 999 /private/job/otel-history export',
                              '3 10 999 /private/job/otel-history.old import',
                              '4 10 999 python3 coordinator.py',
                              '5 10 30 /private/job/otel-history verify'])
        self.assertEqual(OBSERVE.workers(snapshot, 10, Path('/private/job/otel-history')),
                         [{'pid': 1, 'rssBytes': 20480}, {'pid': 5, 'rssBytes': 30720}])

    def test_malformed_rows_are_ignored(self):
        self.assertEqual(OBSERVE.workers('PID PGID RSS COMMAND\nnot-a-process\n1 2 nan binary', 2, Path('binary')), [])
