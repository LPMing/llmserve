#!/usr/bin/env python3
"""Regression tests for invalidating Decode future-arrival wakeups."""

import unittest
from unittest.mock import Mock

from serving.__main__ import (
    _pass_response,
    _scheduler_completion_changed_state,
)


class FlowSimDecodeCompletionWakeupTest(unittest.TestCase):
    def test_token_completion_is_scheduler_state_change(self):
        self.assertTrue(_scheduler_completion_changed_state(
            0, 1, [], 1, 1))

    def test_completed_batch_is_scheduler_state_change(self):
        self.assertTrue(_scheduler_completion_changed_state(
            0, 0, [], 1, 0))

    def test_nonfinal_rank_poll_is_not_state_change(self):
        self.assertFalse(_scheduler_completion_changed_state(
            0, 0, [], 1, 1))

    def test_state_change_invalidates_future_arrival_deadline(self):
        router = Mock()
        router.get_next_pending_arrival.return_value = 13_396_596

        self.assertEqual(
            _pass_response(router, 6_605_088, state_changed=True),
            "pass -1")
        router.get_next_pending_arrival.assert_not_called()


if __name__ == "__main__":
    unittest.main()
