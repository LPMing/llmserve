#!/usr/bin/env python3
"""Regression checks for resolving model-derived P2D sends to real Decode ranks."""

import unittest
from types import SimpleNamespace

from serving.core.graph_generator import pd_decode_graph_kwargs
from serving.core.scheduler import Scheduler
from chakra.src.converter.llm_converter import LLMConverter


class PDDecodeReceiverMappingTest(unittest.TestCase):
    def setUp(self):
        self.instances = [
            {"instance_id": 0, "pd_type": "prefill", "tp_size": 2,
             "pp_size": 1},
            {"instance_id": 1, "pd_type": "decode", "tp_size": 2,
             "pp_size": 1},
        ]
        self.offsets = {0: 0, 1: 4}

    def test_single_decode_is_inferred_as_actual_receiver(self):
        result = pd_decode_graph_kwargs(
            [SimpleNamespace(paired_decode_instance_id=None)], 0,
            self.instances, self.offsets)
        self.assertEqual(result, {
            "pd_decode_offset": 4,
            "pd_decode_tp": 2,
            "pd_decode_pp": 1,
        })

    def test_request_pairing_selects_configured_decode_layout(self):
        instances = self.instances + [
            {"instance_id": 2, "pd_type": "decode", "tp_size": 4,
             "pp_size": 1},
        ]
        offsets = {0: 0, 1: 4, 2: 6}
        result = pd_decode_graph_kwargs(
            [SimpleNamespace(paired_decode_instance_id=2)], 0,
            instances, offsets)
        self.assertEqual(result["pd_decode_offset"], 6)
        self.assertEqual(result["pd_decode_tp"], 4)

    def test_unpaired_multi_decode_is_rejected(self):
        instances = self.instances + [
            {"instance_id": 2, "pd_type": "decode", "tp_size": 2,
             "pp_size": 1},
        ]
        with self.assertRaisesRegex(ValueError, "configure pd_pairing"):
            pd_decode_graph_kwargs(
                [SimpleNamespace(paired_decode_instance_id=None)], 0,
                instances, {0: 0, 1: 4, 2: 6})

    def test_batch_cannot_mix_decode_targets(self):
        instances = self.instances + [
            {"instance_id": 2, "pd_type": "decode", "tp_size": 2,
             "pp_size": 1},
        ]
        requests = [
            SimpleNamespace(paired_decode_instance_id=1),
            SimpleNamespace(paired_decode_instance_id=2),
        ]
        with self.assertRaisesRegex(ValueError, "cannot send P2D KV"):
            pd_decode_graph_kwargs(requests, 0, instances,
                                   {0: 0, 1: 4, 2: 6})

    def test_converter_maps_each_tp_shard_to_real_decode_rank(self):
        converter = LLMConverter(
            "unused", "unused", 2, npu_offset=0,
            pd_decode_offset=4, pd_decode_tp=2, pd_decode_pp=1)
        shard_bytes = 2 * 1024 * 1024
        rank0 = converter._pd_kv_destinations(0, 0, 2, shard_bytes)
        rank1 = converter._pd_kv_destinations(0, 1, 2, shard_bytes)
        self.assertEqual(rank0, [(4, shard_bytes)])
        self.assertEqual(rank1, [(5, shard_bytes)])
        self.assertEqual(sum(size for _, size in rank0 + rank1),
                         2 * shard_bytes)

    def test_legacy_converter_falls_back_to_shadow_ranks(self):
        converter = LLMConverter("unused", "unused", 2, npu_offset=0)
        self.assertEqual(
            converter._pd_kv_destinations(0, 0, 2, 123), [(2, 123)])
        self.assertEqual(
            converter._pd_kv_destinations(0, 1, 2, 123), [(3, 123)])

    def test_batch_graph_start_is_recorded_once_at_submission(self):
        scheduler = Scheduler.__new__(Scheduler)
        scheduler.pd_type = "decode"
        scheduler.start_npu = 8
        scheduler.num_npus = 2
        scheduler.events = []
        scheduler._record_research_event = (
            lambda event, ts, **fields:
            scheduler.events.append((event, ts, fields)))
        request = SimpleNamespace(
            id=17, decode_first_batch_id=3,
            decode_first_batch_start_ns=-1)
        batch = SimpleNamespace(
            execution_start_ns=-1, batch_id=3, requests=[request])

        scheduler.mark_batch_graph_start(batch, 123456)
        scheduler.mark_batch_graph_start(batch, 999999)
        self.assertEqual(request.decode_first_batch_start_ns, 123456)
        self.assertEqual(len(scheduler.events), 1)
        self.assertEqual(scheduler.events[0][0], "BATCH_GRAPH_SUBMITTED")
        self.assertEqual(scheduler.events[0][2]["ranks"], [8, 9])


if __name__ == "__main__":
    unittest.main()
