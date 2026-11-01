import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def module():
    spec = importlib.util.spec_from_file_location('resume_native', ROOT / 'scripts/otel-history-resume-native.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class ResumeNativeTests(unittest.TestCase):
    def test_resume_requires_completed_canonical_native_checks_and_unstarted_tail(self):
        helper = module()
        args = [
            {'success': True, 'fullCanonicalRoundtripVerified': True, 'sourceSamples': 6383043932,
             'sourceCanonicalSHA256': helper.SHA, 'restoredBlock': '/private/01M6BBYTZHHWT579DX99J3S7EF'},
            {'verified': True, 'nativeBinarySHA256': helper.PIN, 'nativeIndexIssueVerificationPassed': True,
             'archiveSHA256Verified': True, 'block': '01M6BBYTZHHWT579DX99J3S7EF'},
            {'samples': 6383043932, 'canonicalSHA256': helper.SHA},
            {'success': False, 'errorType': 'FileNotFoundError'}, {'success': False, 'blocks': []},
            {'phase': 'await-current-native-and-six-original-comparisons'}]
        helper.validate(*args)
        for index, key, value in [(0, 'fullCanonicalRoundtripVerified', False), (1, 'nativeIndexIssueVerificationPassed', False),
                (1, 'nativeBinarySHA256', 'wrong'), (2, 'samples', 120), (3, 'success', True),
                (4, 'blocks', [{'started': True}]), (5, 'phase', 'import')]:
            changed = copy.deepcopy(args)
            changed[index][key] = value
            with self.assertRaises(ValueError):helper.validate(*changed)
