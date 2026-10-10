#!/usr/bin/env python3
"""Small semantic regression test for P/D Decode max_num_seqs admission."""

import unittest

from serving.core.request import Request, RequestStatus
from serving.core.scheduler import Scheduler


class _KV:
    def get_computed_blocks(self, _request):
        return [], 0, 0

    def allocate_slots(self, _request, _num_new, *_args):
        return []

    def take_traffic(self):
        return 0, 0


class _Memory:
    @staticmethod
    def record_prefix_stats(_request):
        pass


class _Logger:
    @staticmethod
    def info(*_args, **_kwargs):
        pass


def _decode_request(request_id, source_arrival, ready_time):
    req = Request(request_id, "test/model", 4, 8, source_arrival, 9)
    req.num_computed_tokens = 4
    req.num_tokens_reached = 5
    req.p2d_kv_ready_time_ns = ready_time
    return req


def _scheduler(max_num_seqs, running):
    scheduler = Scheduler.__new__(Scheduler)
    scheduler.instance_id = 9
    scheduler.pd_type = "decode"
    scheduler.max_num_seqs = max_num_seqs
    scheduler.max_num_batched_tokens = 128
    scheduler.long_prefill_token_threshold = 0
    scheduler.enable_chunked_prefill = False
    scheduler.reserve_full_isl = False
    scheduler.running = list(running)
    scheduler.waiting = []
    scheduler.inflight = []
    scheduler.decode_handoff_waiters = {}
    scheduler.kv = _KV()
    scheduler.memory = _Memory()
    scheduler.logger = _Logger()
    scheduler.recompute_tokens = 0
    return scheduler


class DecodeCapacityAdmissionTest(unittest.TestCase):
    def test_ready_handoff_waits_when_max_sequences_full(self):
        incumbent = object()
        scheduler = _scheduler(max_num_seqs=1, running=[incumbent])
        req = _decode_request(1, source_arrival=10, ready_time=100)

        scheduler.add_decode(req, completion_time_ns=100)
        self.assertEqual(scheduler.running, [incumbent])
        self.assertEqual(scheduler.waiting, [req])
        self.assertEqual(req.status, RequestStatus.WAITING)
        self.assertEqual(req.decode_capacity_queue_enter_time_ns, 100)
        self.assertEqual(req.decode_running_at_handoff, 1)
        self.assertEqual(req.decode_max_num_seqs_at_handoff, 1)

        scheduled = []
        remaining = scheduler._schedule_waiting(
            current=150, scheduled=scheduled, token_budget=16)
        self.assertEqual(remaining, 16)
        self.assertEqual(scheduler.waiting, [req])
        self.assertEqual(scheduled, [])

        scheduler.running.remove(incumbent)
        remaining = scheduler._schedule_waiting(
            current=200, scheduled=scheduled, token_budget=16)
        self.assertEqual(remaining, 15)
        self.assertEqual(scheduler.waiting, [])
        self.assertEqual(scheduler.running, [req])
        self.assertEqual(req.status, RequestStatus.RUNNING)
        self.assertEqual(req.decode_capacity_queue_wait_ns, 100)
        self.assertEqual(scheduled, [(req, 1, 4)])

    def test_under_capacity_handoff_keeps_fast_path(self):
        scheduler = _scheduler(max_num_seqs=2, running=[])
        req = _decode_request(2, source_arrival=10, ready_time=100)
        scheduler.add_decode(req, completion_time_ns=100)

        self.assertEqual(scheduler.running, [req])
        self.assertEqual(scheduler.waiting, [])
        self.assertEqual(req.status, RequestStatus.RUNNING)
        self.assertEqual(req.decode_capacity_queue_enter_time_ns, -1)

    def test_capacity_waiters_order_by_decode_ready_time(self):
        scheduler = _scheduler(max_num_seqs=1, running=[object()])
        later_ready = _decode_request(3, source_arrival=0, ready_time=200)
        earlier_ready = _decode_request(4, source_arrival=100, ready_time=150)

        scheduler.add_decode(later_ready, completion_time_ns=200)
        scheduler.add_decode(earlier_ready, completion_time_ns=150)

        self.assertEqual(scheduler.waiting, [earlier_ready, later_ready])


if __name__ == "__main__":
    unittest.main()
