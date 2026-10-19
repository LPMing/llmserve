#!/usr/bin/env python3
"""Physical-rank mapping and shared 200-Gbps cut regression tests."""

import json
import tempfile
import unittest
from pathlib import Path

from serving.core.flowsim_backend import FlowSpec, PersistentFluidFlowNetwork


ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "experiments/pd_kv_ep/configs/large_scale"


class FlowSimRankMappingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.topology = FIXTURE / "flowsim/minimal_1p2d_ep16_single_tor_nvlink.txt"
        with (FIXTURE / "minimal_1p2d_ep16_logical_to_physical.json").open() as stream:
            cls.rank_map = json.load(stream)["logical_to_physical"]

    def test_p2d_and_decode_ep_map_onto_same_physical_tor_egress(self):
        network = PersistentFluidFlowNetwork(
            str(self.topology), rank_map=self.rank_map)
        isolated = PersistentFluidFlowNetwork(
            str(self.topology), rank_map=self.rank_map)
        isolated.simulate([FlowSpec(
            "kv-isolated", 0, 2, 1_000_000, 0,
            "KV_MOVEMENT", "P2D", request_ids=(10,))])
        isolated_kv_end = isolated.last_flows[0]["end_ns"]
        ep_isolated = PersistentFluidFlowNetwork(
            str(self.topology), rank_map=self.rank_map)
        ep_isolated.simulate([FlowSpec(
            "ep-isolated", 24, 16, 1_000_000, 0,
            "EP", "EP_DISPATCH", request_ids=(11,))])
        isolated_ep_end = ep_isolated.last_flows[0]["end_ns"]

        network.simulate([
            # Prefill logical rank 0 -> P0 GPU0; paired shadow rank 2 aliases
            # the actual D0 GPU0 endpoint (physical endpoint 8).
            FlowSpec("kv-r0", 0, 2, 1_000_000, 0,
                     "KV_MOVEMENT", "P2D", request_ids=(10,)),
            # D1 GPU0 -> D0 GPU0, sharing directed ToR->D0-NIC egress.
            FlowSpec("ep-r1", 24, 16, 1_000_000, 0,
                     "EP", "EP_DISPATCH", request_ids=(11,)),
        ])
        by_id = {row["flow_id"]: row for row in network.last_flows}
        self.assertEqual(by_id["kv-r0"]["src"], 0)
        self.assertEqual(by_id["kv-r0"]["dst"], 8)
        self.assertEqual(by_id["kv-r0"]["logical_src"], 0)
        self.assertEqual(by_id["kv-r0"]["logical_dst"], 2)
        self.assertEqual(by_id["ep-r1"]["src"], 16)
        self.assertEqual(by_id["ep-r1"]["dst"], 8)
        self.assertEqual(by_id["ep-r1"]["logical_src"], 24)
        self.assertEqual(by_id["ep-r1"]["logical_dst"], 16)
        self.assertIn("30->26", by_id["kv-r0"]["path"])
        self.assertIn("30->26", by_id["ep-r1"]["path"])
        self.assertEqual(by_id["kv-r0"]["end_ns"],
                         by_id["ep-r1"]["end_ns"])
        self.assertGreater(by_id["kv-r0"]["end_ns"], isolated_kv_end)
        self.assertGreater(by_id["ep-r1"]["end_ns"], isolated_ep_end)
        self.assertEqual(isolated_kv_end, 50_200)
        self.assertEqual(isolated_ep_end, 50_200)
        self.assertEqual(by_id["kv-r0"]["end_ns"], 90_200)
        self.assertEqual(by_id["ep-r1"]["end_ns"], 90_200)
        for flow in network.last_flows:
            self.assertEqual(flow["bytes"], 1_000_000)
            self.assertGreaterEqual(flow["end_ns"], flow["start_ns"])

    def test_map_rejects_missing_logical_rank(self):
        network = PersistentFluidFlowNetwork(
            str(self.topology), rank_map={0: 0})
        with self.assertRaisesRegex(ValueError, "misses logical endpoint"):
            network.submit([FlowSpec(
                "unmapped", 0, 16, 1, 0, "EP", "EP_DISPATCH")])

    def test_topology_header_must_match_physical_link_records(self):
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as stream:
            stream.write("34 4 58\n30 31 32 33\n")
            stream.flush()
            with self.assertRaisesRegex(ValueError, "declares 58 physical links"):
                PersistentFluidFlowNetwork(stream.name)

    def test_same_server_ep_uses_local_nvlink_graph(self):
        network = PersistentFluidFlowNetwork(
            str(self.topology), rank_map=self.rank_map)
        p2d_only = PersistentFluidFlowNetwork(
            str(self.topology), rank_map=self.rank_map)
        p2d_only.simulate([FlowSpec(
            "p2d-only", 0, 2, 1_000_000, 0,
            "KV_MOVEMENT", "P2D", request_ids=(10,))])
        isolated_p2d_end = p2d_only.last_flows[0]["end_ns"]

        network.simulate([
            # Logical ranks 16 and 20 map to D0 GPUs 8 and 12. These GPUs
            # attach to separate NIC rails but share local switch 32.
            FlowSpec("local-ep", 16, 20, 1_000_000, 0,
                     "EP", "EP_DISPATCH"),
            FlowSpec("p2d", 0, 2, 1_000_000, 0,
                     "KV_MOVEMENT", "P2D", request_ids=(10,)),
        ])
        by_id = {row["flow_id"]: row for row in network.last_flows}
        local_path = by_id["local-ep"]["path"]
        self.assertEqual(local_path, ["8->32", "32->12"])
        self.assertFalse(any("30" in link.split("->") for link in local_path))
        self.assertIn("30->26", by_id["p2d"]["path"])
        self.assertTrue(set(local_path).isdisjoint(by_id["p2d"]["path"]))
        self.assertEqual(by_id["p2d"]["end_ns"], isolated_p2d_end)

    def test_every_same_server_gpu_pair_avoids_nic_and_tor(self):
        network = PersistentFluidFlowNetwork(str(self.topology))
        for first_gpu, local_switch in ((0, 31), (8, 32), (16, 33)):
            for src in range(first_gpu, first_gpu + 8):
                for dst in range(first_gpu, first_gpu + 8):
                    if src == dst:
                        continue
                    path = network.path(src, dst)
                    self.assertEqual(path, [(src, local_switch),
                                            (local_switch, dst)])
                    self.assertFalse(any(30 in link for link in path))
                    self.assertFalse(any(24 <= node <= 29
                                         for link in path for node in link))

    def test_cross_server_ep_still_uses_tor_and_200g_uplinks(self):
        network = PersistentFluidFlowNetwork(
            str(self.topology), rank_map=self.rank_map)
        network.simulate([FlowSpec(
            "cross-server-ep", 24, 16, 1_000_000, 0,
            "EP", "EP_DISPATCH")])
        flow = network.last_flows[0]
        self.assertEqual(flow["path"], [
            "16->28", "28->30", "30->26", "26->8"])
        for link in ((28, 30), (30, 26)):
            self.assertEqual(network._edge(link)["capacity_Bps"],
                             200_000_000_000 / 8)

    def test_decode_opportunity_map_shares_p2d_and_ep_directed_cut(self):
        topology = ROOT / (
            "research_motivation/decode_opportunity/"
            "two_prefill_two_decode_shared_cut_200g.txt")
        with (ROOT / "research_motivation/decode_opportunity/"
              "rank_map_2p2d_tp2_cross_cut.json").open() as stream:
            rank_map = json.load(stream)["logical_to_physical"]
        network = PersistentFluidFlowNetwork(str(topology), rank_map=rank_map)

        # P0 shard 1 -> D1 rank 1 and D1's cross-leaf EP peer both
        # traverse the same directed 12->13 cut.
        p2d_path = network.path(rank_map[0], rank_map[3])
        ep_path = network.path(rank_map[10], rank_map[11])
        self.assertIn((12, 13), p2d_path)
        self.assertIn((12, 13), ep_path)
        self.assertEqual(
            network._edge((12, 13))["capacity_Bps"], 25_000_000_000)


if __name__ == "__main__":
    unittest.main()
