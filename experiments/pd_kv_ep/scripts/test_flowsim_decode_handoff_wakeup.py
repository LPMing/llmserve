#!/usr/bin/env python3
"""Regression tests for waking Decode after a P2D-ready handoff."""

import unittest
from unittest.mock import Mock

from serving.core.flowsim_worker import Worker


def _worker():
    worker = Worker.__new__(Worker)
    worker.executor = Mock()
    worker.decode_ranks = {1, 2}
    worker.now = 100
    worker.sleeping = [False, False, False]
    worker._wake_unscheduled_ranks = Mock()
    worker._schedule = Mock()
    return worker


class FlowSimDecodeHandoffWakeupTest(unittest.TestCase):
    def test_handoff_wakeup_is_carried_with_prefill_done_response(self):
        worker = _worker()

        worker._command(0, "wake-decode done")

        worker._wake_unscheduled_ranks.assert_called_once_with(
            allowed={1, 2})
        self.assertTrue(worker.sleeping[0])

    def test_handoff_wakeup_can_accompany_next_prefill_graph(self):
        worker = _worker()

        worker._command(0, "wake-decode /tmp/prefill-graph")

        worker._wake_unscheduled_ranks.assert_called_once_with(
            allowed={1, 2})
        worker._schedule.assert_called_once_with(
            [0], "/tmp/prefill-graph")

    def test_pass_minus_one_does_not_duplicate_decode_wakeup(self):
        worker = _worker()

        worker._command(0, "wake-decode pass -1")

        worker._wake_unscheduled_ranks.assert_called_once_with(
            exclude_rank=0, allowed={1, 2})


if __name__ == "__main__":
    unittest.main()
