#!/usr/bin/env python3
"""Regression: zero-cost PP messages still preserve cross-stage causality."""

import unittest
from types import SimpleNamespace

from serving.core.flowsim_worker import AsyncGraphExecutor


def _job():
    comm_key = (0, 2, 91, 4096)
    nodes = {
        (0, 1): {
            "kind": "p2p", "class": "OTHER", "subtype": "OTHER",
            "node": SimpleNamespace(name="pp_activation_send"),
            "comm_key": comm_key, "is_send": True,
        },
        (2, 2): {
            "kind": "p2p", "class": "OTHER", "subtype": "OTHER",
            "node": SimpleNamespace(name="pp_activation_recv"),
            "comm_key": comm_key, "is_send": False,
        },
    }
    return {
        "id": 7, "nodes": nodes, "node_finish": {}, "children": {},
        "unresolved": {}, "completed": False,
    }


class LocalPPCausalityTest(unittest.TestCase):
    def _executor(self):
        executor = AsyncGraphExecutor.__new__(AsyncGraphExecutor)
        executor.network_classes = {"KV_MOVEMENT", "EP"}
        return executor

    def test_receiver_waits_for_later_sender(self):
        executor = self._executor()
        job = _job()
        executor._activate_p2p(job, (2, 2), 0)
        self.assertNotIn((2, 2), job["node_finish"])
        executor._activate_p2p(job, (0, 1), 1_000_000)
        self.assertEqual(job["node_finish"][(0, 1)], 1_000_000)
        self.assertEqual(job["node_finish"][(2, 2)], 1_000_000)

    def test_sender_completes_but_later_receiver_observes_message(self):
        executor = self._executor()
        job = _job()
        executor._activate_p2p(job, (0, 1), 1_000_000)
        self.assertEqual(job["node_finish"][(0, 1)], 1_000_000)
        self.assertNotIn((2, 2), job["node_finish"])
        executor._activate_p2p(job, (2, 2), 1_500_000)
        self.assertEqual(job["node_finish"][(0, 1)], 1_000_000)
        self.assertEqual(job["node_finish"][(2, 2)], 1_500_000)

    def test_p2d_cannot_be_silently_removed_from_network(self):
        executor = self._executor()
        job = _job()
        job["nodes"][(0, 1)]["subtype"] = "P2D"
        job["nodes"][(0, 1)]["class"] = "KV_MOVEMENT"
        executor.network_classes = {"EP"}
        with self.assertRaisesRegex(RuntimeError, "cannot be excluded"):
            executor._activate_p2p(job, (0, 1), 100)


if __name__ == "__main__":
    unittest.main()
