"""Decode KV credit must exist before Prefill can emit handoff bytes."""

import unittest

from serving.core.block_pool import BlockPool, Device
from serving.core.kv_cache_manager import TieredKVCacheManager, request_block_hashes
from serving.core.scheduler import Scheduler


class _Req:
    def __init__(self, ident):
        self.id = ident
        self.input_hash_ids = list(range(ident * 100, ident * 100 + 16))
        self.output_hash_ids = []
        self.original_input = 16
        self.num_computed_tokens = 0
        self.num_tokens_reached = 16
        self.block_hashes = None
        self.storage_hit_pool = None
        self.storage_hit_blocks = 0
        self.paired_decode_instance_id = 9
        self.destination_prefix_reservation = None
        self.destination_prefix_reuse_tokens = 0


def _manager():
    pool = BlockPool(Device.NPU, 2, 16, 4096, enable_caching=True)
    return TieredKVCacheManager(16, pool, [], enable_caching=True)


class HandoffCapacityCreditTest(unittest.TestCase):
    def test_incomplete_prompt_ids_cannot_hash_future_output(self):
        req = _Req(4)
        req.original_input = 32
        req.output_hash_ids = list(range(200, 216))
        self.assertEqual(request_block_hashes(req, 16), [])

    def test_unsplittable_recomputation_above_budget_fails_fast(self):
        scheduler = Scheduler.__new__(Scheduler)
        scheduler.waiting = [_Req(3)]
        scheduler.running = []
        scheduler.max_num_seqs = 8
        scheduler.max_num_batched_tokens = 2048
        scheduler.enable_chunked_prefill = False
        scheduler.long_prefill_token_threshold = 0
        scheduler.pd_type = "decode"
        scheduler.kv = type("KV", (), {
            "get_computed_blocks": lambda self, req: ([], 0, 0)})()
        scheduler._record_research_event = lambda *args, **kwargs: None
        req = scheduler.waiting[0]
        req.arrival = 0
        req.num_tokens = 2300
        req.num_preemptions = 1
        with self.assertRaisesRegex(ValueError, "enable chunked prefill"):
            scheduler._schedule_waiting(0, [], 2048)

    def test_full_transfer_credit_blocks_then_retries_without_leak(self):
        peer = Scheduler.__new__(Scheduler)
        peer.instance_id = 9
        peer.kv = _manager()
        peer._prefix_cache_compatibility_key = lambda: ("model", 1)
        prefill = Scheduler.__new__(Scheduler)
        prefill.pd_type = "prefill"
        prefill.pd_handoff_capacity_reservation = True
        prefill.destination_prefix_handoff = "DISABLED"
        prefill.destination_decode_schedulers = {9: peer}
        events = []
        prefill._record_research_event = lambda event, timestamp, **data: (
            events.append((event, timestamp, data)))

        first = _Req(1)
        second = _Req(2)
        self.assertTrue(prefill._reserve_destination_handoff_capacity(first, 0))
        self.assertEqual(first.destination_prefix_reuse_tokens, 0)
        self.assertEqual(peer.kv.npu_pool.get_num_free_blocks(), 0)
        self.assertFalse(prefill._reserve_destination_handoff_capacity(second, 1))
        self.assertEqual(peer.kv.npu_pool.get_num_free_blocks(), 0)
        self.assertNotIn(second.id, peer.kv.handoff_reservations)
        self.assertEqual(events[-1][0], "HANDOFF_CAPACITY_WAIT")

        first.num_computed_tokens = first.original_input
        committed = peer.kv.commit_handoff_reservation(
            first, peer._prefix_cache_compatibility_key())
        self.assertEqual(committed["hit_tokens"], 0)
        peer.kv.free(first)
        self.assertTrue(prefill._reserve_destination_handoff_capacity(second, 2))
        self.assertEqual(peer.kv.npu_pool.get_num_free_blocks(), 0)
        peer.kv.free(second)
        self.assertEqual(peer.kv.npu_pool.get_num_free_blocks(), 2)


if __name__ == "__main__":
    unittest.main()
