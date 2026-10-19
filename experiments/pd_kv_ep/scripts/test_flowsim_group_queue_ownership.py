#!/usr/bin/env python3
"""DP/EP FlowSim group commands find graph owners across local TP ranks."""

import unittest
from collections import deque

from serving.core.flowsim_groups import (
    instance_group_command,
    queued_group_graph_owners,
)


class FlowSimGroupQueueOwnershipTest(unittest.TestCase):
    def test_instance_command_includes_all_unique_sorted_ranks(self):
        self.assertEqual(
            instance_group_command("/run/instance2_batch1/llm", [9, 8, 9]),
            "group /run/instance2_batch1/llm 8,9")

    def test_instance_command_rejects_empty_rank_group(self):
        with self.assertRaises(ValueError):
            instance_group_command("/run/empty/llm", [])

    def test_nonleader_tp_rank_can_own_member_graph(self):
        path = "/run/dp_decode_ep_batch1/llm"
        queues = {31: deque([path]), 29: deque([path])}
        ranges = [(28, 2), (30, 2)]
        owners, blockers = queued_group_graph_owners(
            ranges, path, current_rank=28, queued_workloads=queues)
        self.assertEqual(owners, [29, 31])
        self.assertEqual(blockers, [])

    def test_member_without_graph_owner_blocks_group_submission(self):
        path = "/run/dp_decode_ep_batch1/llm"
        queues = {29: deque([path])}
        owners, blockers = queued_group_graph_owners(
            [(28, 2), (30, 2)], path, current_rank=28,
            queued_workloads=queues)
        self.assertEqual(owners, [29])
        self.assertEqual(blockers, [(30, "missing", None)])

    def test_fifo_mismatch_blocks_later_group_graph(self):
        queues = {
            29: deque(["/run/older/llm", "/run/current/llm"]),
            31: deque(["/run/current/llm"]),
        }
        owners, blockers = queued_group_graph_owners(
            [(28, 2), (30, 2)], "/run/current/llm", current_rank=28,
            queued_workloads=queues)
        self.assertEqual(owners, [31])
        self.assertEqual(blockers, [(29, "queued", "/run/older/llm")])


if __name__ == "__main__":
    unittest.main()
