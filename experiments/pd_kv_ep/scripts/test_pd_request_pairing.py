#!/usr/bin/env python3
"""A P/D request keeps its paired Decode instance from arrival to handoff."""

import unittest

from serving.core.request import Request
from serving.core.router import Router


class _Scheduler:
    def __init__(self, instance_id, pd_type):
        self.instance_id = instance_id
        self.pd_type = pd_type
        self.enable_prefix_caching = False
        self.model = "test/model"
        self.waiting = []
        self.received = []

    def add_request(self, values, is_init=True, paired_decode_instance_id=None):
        request = Request(*values, is_init=is_init)
        request.paired_decode_instance_id = paired_decode_instance_id
        self.waiting.append(request)
        return request

    def add_decode(self, request, completion_time_ns=None):
        self.received.append((request, completion_time_ns))


class PDRequestPairingTest(unittest.TestCase):
    def test_paired_decode_is_selected_before_prefill_and_kept_at_handoff(self):
        prefill0 = _Scheduler(0, "prefill")
        prefill1 = _Scheduler(1, "prefill")
        decode2 = _Scheduler(2, "decode")
        decode3 = _Scheduler(3, "decode")
        router = Router(
            4, [prefill0, prefill1, decode2, decode3], 1,
            routing_policy="RR", pd_pairing={0: 3, 1: 2})
        router._pending_requests = [{
            "index": 77,
            "input_toks": 128,
            "output_toks": 132,
            "arrival_time_ns": 0,
        }]
        router._pending_idx = 0
        router.route_arrived_requests(0)
        request = prefill0.waiting[0]
        self.assertEqual(request.paired_decode_instance_id, 3)

        router.transfer_prefill_request([request], completion_time_ns=1234)
        self.assertEqual(decode2.received, [])
        self.assertEqual(decode3.received, [(request, 1234)])


if __name__ == "__main__":
    unittest.main()
