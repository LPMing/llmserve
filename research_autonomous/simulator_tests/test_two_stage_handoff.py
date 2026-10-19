"""Source KV ownership and receiver credit survive held/in-flight cancellation."""

import unittest
from types import SimpleNamespace

from serving.core.block_pool import BlockPool, Device
from serving.core.kv_cache_manager import TieredKVCacheManager
from serving.core.request import RequestStatus
from serving.core.scheduler import Scheduler


def manager(blocks=2, caching=False):
    return TieredKVCacheManager(
        16, BlockPool(Device.NPU, blocks, 16, 4096,
                      enable_caching=caching),
        [], enable_caching=caching)


def request(ident):
    return SimpleNamespace(
        id=ident, original_input=16, num_computed_tokens=0,
        num_tokens_reached=17, input_hash_ids=None, output_hash_ids=None,
        block_hashes=None, storage_hit_pool=None, storage_hit_blocks=0,
        paired_decode_instance_id=9, destination_prefix_reservation=None,
        destination_prefix_reuse_tokens=0, handoff_cancelled=False,
        status=RequestStatus.HANDOFF_WAIT)


def schedulers():
    peer = Scheduler.__new__(Scheduler)
    peer.instance_id = 9
    peer.kv = manager()
    peer._prefix_cache_compatibility_key = lambda: ("test",)
    source = Scheduler.__new__(Scheduler)
    source.pd_type = "prefill"
    source.model = "test-model"
    source.kv = manager()
    source.source_held = []
    source.inflight = []
    source.running = []
    source.batch_ids = -1
    source.start_npu = 0
    source.num_npus = 1
    source.actual_pd_receivers = True
    source.pd_handoff_capacity_reservation = True
    source.destination_prefix_handoff = "DISABLED"
    source.destination_decode_schedulers = {9: peer}
    source.logger = SimpleNamespace(info=lambda *args, **kwargs: None)
    source._record_research_event = lambda *args, **kwargs: None
    return source, peer


class TwoStageHandoffTest(unittest.TestCase):
    def test_late_credit_pins_prefix_and_sets_delta(self):
        source, peer = schedulers()
        peer.kv = manager(blocks=4, caching=True)
        warm = request(8)
        warm.input_hash_ids = list(range(16))
        peer.kv.allocate_slots(warm, 16)
        warm.num_computed_tokens = 16
        peer.kv.cache_blocks(warm, 16)
        peer.kv.free(warm)

        req = request(9)
        req.original_input = 32
        req.num_tokens_reached = 33
        req.input_hash_ids = list(range(16)) + list(range(100, 116))
        source.kv.allocate_slots(req, 32)
        req.num_computed_tokens = 32
        source.source_held.append(req)
        source.destination_prefix_handoff = "DELTA"
        batch = source._schedule_held_handoff(10, 0)
        self.assertIsNotNone(batch)
        self.assertEqual(req.destination_prefix_reuse_tokens, 16)
        self.assertEqual(req.destination_prefix_reservation["required_blocks"], 3)
        self.assertIn(req.id, source.kv.req_to_blocks)
        self.assertEqual(peer.kv.npu_pool.get_num_free_blocks(), 1)

    def test_cancel_held_releases_source_without_receiver_credit(self):
        source, peer = schedulers()
        req = request(10)
        source.kv.allocate_slots(req, 16)
        req.num_computed_tokens = 16
        source.source_held.append(req)
        self.assertEqual(source.kv.npu_pool.get_num_free_blocks(), 1)
        self.assertTrue(source.cancel_held_handoff(req.id, 5))
        self.assertEqual(source.kv.npu_pool.get_num_free_blocks(), 2)
        self.assertEqual(peer.kv.npu_pool.get_num_free_blocks(), 2)
        self.assertFalse(source.source_held)

    def test_cancel_inflight_releases_both_after_graph_completion(self):
        source, peer = schedulers()
        req = request(11)
        source.kv.allocate_slots(req, 16)
        req.num_computed_tokens = 16
        source.source_held.append(req)
        batch = source._schedule_held_handoff(10, 0)
        self.assertIsNotNone(batch)
        self.assertEqual(peer.kv.npu_pool.get_num_free_blocks(), 0)
        self.assertEqual(source.kv.npu_pool.get_num_free_blocks(), 1)
        self.assertTrue(source.cancel_held_handoff(req.id, 11))
        _, _, handed_off = source.add_done(batch.batch_id + 1, 0, 20)
        self.assertEqual(handed_off, [])
        self.assertEqual(source.kv.npu_pool.get_num_free_blocks(), 2)
        self.assertEqual(peer.kv.npu_pool.get_num_free_blocks(), 2)
        self.assertFalse(source.inflight)


if __name__ == "__main__":
    unittest.main()
