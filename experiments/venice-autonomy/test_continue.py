"""Tests for the continuation policy of the repository runner."""
import unittest

from attempt import continue_openhands
from repository_runner import apply_continuation_policy


class Conversation:
    """Fake agent conversation with scriptable failures."""

    def __init__(self, failures=0) -> None:
        """Initialize the conversation fixture."""

        self.failures = failures
        self.runs = 0
        self.messages: list[str] = []

    def run(self):
        """Run once, failing while the configured failure budget lasts."""
        self.runs += 1
        if self.runs <= self.failures:
            msg = "provider failed"
            raise RuntimeError(msg)

    def send_message(self, message):
        """Record a follow-up message sent to the conversation."""
        self.messages.append(message)


def facts(continue_value):
    def acceptance(sandbox, directory, round_number) -> dict[str, object]:
        return {
            "round": round_number,
            "continue": continue_value,
            "accepted": continue_value is not True,
        }

    return acceptance


class ContinueOpenHandsTests(unittest.TestCase):
    """Tests for the continue_openhands acceptance handshake."""

    def test_acceptance_none_runs_once_without_messages(self):
        """Verify continue=None runs once and sends no follow-up."""
        conversation = Conversation()
        continue_openhands(conversation, None, None, None)
        self.assertEqual(conversation.runs, 1)
        self.assertEqual(conversation.messages, [])

    def test_continue_false_stops_without_follow_up(self):
        """Verify continue=false stops the run without a follow-up."""
        conversation = Conversation()
        self.assertEqual(continue_openhands(conversation, None, None, facts(False)), "stopped")
        self.assertEqual(conversation.runs, 1)
        self.assertEqual(conversation.messages, [])

    def test_reject_then_accept_runs_twice_with_one_follow_up(self):
        """Verify a rejected then accepted continue runs twice with one message."""
        conversation = Conversation()
        decisions = iter([True, False])

        def acceptance(sandbox, directory, round_number) -> dict[str, object]:
            return {"round": round_number, "continue": next(decisions)}

        continue_openhands(conversation, None, None, acceptance)
        self.assertEqual(conversation.runs, 2)
        self.assertEqual(len(conversation.messages), 1)
        self.assertIn("Continue in this same conversation", conversation.messages[0])
        self.assertIn("No transport request is replayed", conversation.messages[0])

    def test_persistent_rejection_stops_at_three_and_states_exhaustion(self):
        """Verify persistent rejection stops after three runs with an exhaustion notice."""
        conversation = Conversation()
        outcome = continue_openhands(conversation, None, None, facts(True))
        self.assertEqual(outcome, "exhausted")
        self.assertEqual(conversation.runs, 3)
        self.assertEqual(len(conversation.messages), 2)
        self.assertTrue(
            all(
                "Continue in this same conversation" in message for message in conversation.messages
            )
        )
        self.assertTrue(
            all(
                "continuation budget is exhausted" not in message
                for message in conversation.messages
            )
        )

    def test_provider_exception_is_not_replayed(self):
        """Verify a provider exception aborts without replaying."""
        conversation = Conversation(failures=1)
        with self.assertRaises(RuntimeError):
            continue_openhands(conversation, None, None, facts(True))
        self.assertEqual(conversation.runs, 1)
        self.assertEqual(conversation.messages, [])

    def test_non_boolean_continue_does_not_authorize_another_run(self):
        """Verify a non-boolean continue value stops further runs."""
        conversation = Conversation()
        continue_openhands(conversation, None, None, facts("true"))
        continue_openhands(conversation, None, None, facts(1))
        self.assertEqual(conversation.runs, 2)
        self.assertEqual(conversation.messages, [])


class ContinuationPolicyTests(unittest.TestCase):
    """Tests for apply_continuation_policy decisions."""

    def test_real_rejection_continues_until_two_unchanged_rounds(self):
        """Verify real rejection continues until two no-progress rounds."""
        first = apply_continuation_policy({"accepted": False, "consecutive_no_progress": 0}, 0)
        second = apply_continuation_policy({"accepted": False, "consecutive_no_progress": 1}, 1)
        third = apply_continuation_policy({"accepted": False, "consecutive_no_progress": 2}, 2)
        self.assertTrue(first["continue"])
        self.assertTrue(second["continue"])
        self.assertFalse(third["continue"])
        self.assertFalse(first["real_accepted"])

    def test_force_once_rejects_only_the_first_round(self):
        """Verify a forced continue authorizes only the first round."""
        forced = apply_continuation_policy(
            {"accepted": True, "consecutive_no_progress": 0}, 0, True
        )
        later = apply_continuation_policy({"accepted": True, "consecutive_no_progress": 0}, 1, True)
        self.assertTrue(forced["real_accepted"])
        self.assertFalse(forced["accepted"])
        self.assertTrue(forced["continue"])
        self.assertTrue(forced["forced_rejection"])
        self.assertTrue(later["accepted"])
        self.assertFalse(later["continue"])
        self.assertNotIn("forced_rejection", later)


if __name__ == "__main__":
    unittest.main()
