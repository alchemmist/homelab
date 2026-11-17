import unittest

from attempt import continue_openhands
from repository_runner import apply_continuation_policy


class Conversation:
    def __init__(self, failures=0):
        self.failures = failures
        self.runs = 0
        self.messages = []

    def run(self):
        self.runs += 1
        if self.runs <= self.failures:
            raise RuntimeError('provider failed')

    def send_message(self, message):
        self.messages.append(message)


def facts(continue_value):
    def acceptance(sandbox, directory, round_number):
        return {'round': round_number, 'continue': continue_value, 'accepted': continue_value is not True}
    return acceptance


class ContinueOpenHandsTests(unittest.TestCase):
    def test_acceptance_none_runs_once_without_messages(self):
        conversation = Conversation()
        continue_openhands(conversation, None, None, None)
        self.assertEqual(conversation.runs, 1)
        self.assertEqual(conversation.messages, [])

    def test_continue_false_stops_without_follow_up(self):
        conversation = Conversation()
        continue_openhands(conversation, None, None, facts(False))
        self.assertEqual(conversation.runs, 1)
        self.assertEqual(conversation.messages, [])

    def test_reject_then_accept_runs_twice_with_one_follow_up(self):
        conversation = Conversation()
        decisions = iter([True, False])

        def acceptance(sandbox, directory, round_number):
            return {'round': round_number, 'continue': next(decisions)}

        continue_openhands(conversation, None, None, acceptance)
        self.assertEqual(conversation.runs, 2)
        self.assertEqual(len(conversation.messages), 1)
        self.assertIn('Continue in this same conversation', conversation.messages[0])
        self.assertIn('No transport request is replayed', conversation.messages[0])

    def test_persistent_rejection_stops_at_three_and_states_exhaustion(self):
        conversation = Conversation()
        continue_openhands(conversation, None, None, facts(True))
        self.assertEqual(conversation.runs, 3)
        self.assertEqual(len(conversation.messages), 3)
        self.assertTrue(all('Continue in this same conversation' in message for message in conversation.messages[:2]))
        self.assertIn('continuation budget is exhausted', conversation.messages[2])
        self.assertNotIn('Continue in this same conversation', conversation.messages[2])

    def test_provider_exception_is_not_replayed(self):
        conversation = Conversation(failures=1)
        with self.assertRaises(RuntimeError):
            continue_openhands(conversation, None, None, facts(True))
        self.assertEqual(conversation.runs, 1)
        self.assertEqual(conversation.messages, [])

    def test_non_boolean_continue_does_not_authorize_another_run(self):
        conversation = Conversation()
        continue_openhands(conversation, None, None, facts('true'))
        continue_openhands(conversation, None, None, facts(1))
        self.assertEqual(conversation.runs, 2)
        self.assertEqual(conversation.messages, [])


class ContinuationPolicyTests(unittest.TestCase):
    def test_real_rejection_continues_until_two_unchanged_rounds(self):
        first = apply_continuation_policy({'accepted': False, 'consecutive_no_progress': 0}, 0)
        second = apply_continuation_policy({'accepted': False, 'consecutive_no_progress': 1}, 1)
        third = apply_continuation_policy({'accepted': False, 'consecutive_no_progress': 2}, 2)
        self.assertTrue(first['continue'])
        self.assertTrue(second['continue'])
        self.assertFalse(third['continue'])
        self.assertFalse(first['real_accepted'])

    def test_force_once_rejects_only_the_first_round(self):
        forced = apply_continuation_policy({'accepted': True, 'consecutive_no_progress': 0}, 0, True)
        later = apply_continuation_policy({'accepted': True, 'consecutive_no_progress': 0}, 1, True)
        self.assertTrue(forced['real_accepted'])
        self.assertFalse(forced['accepted'])
        self.assertTrue(forced['continue'])
        self.assertTrue(forced['forced_rejection'])
        self.assertTrue(later['accepted'])
        self.assertFalse(later['continue'])
        self.assertNotIn('forced_rejection', later)


if __name__ == '__main__':
    unittest.main()
