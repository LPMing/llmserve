import unittest

from serving.core.flowsim_backend import FlowSpec, PersistentFluidFlowNetwork


TOPOLOGY = (
    "research_motivation/decode_opportunity/"
    "two_prefill_two_decode_shared_cut_200g.txt")


class KVRequestFirstTest(unittest.TestCase):
    def test_prioritizes_all_required_shards_of_one_request(self):
        network = PersistentFluidFlowNetwork(
            TOPOLOGY, policy="KV_REQUEST_FIRST", request_first_id=3)
        active = {
            "r2-s0": {"spec": FlowSpec(
                "r2-s0", 0, 10, 100, 0, "KV_MOVEMENT", "P2D",
                request_ids=(2,))},
            "r2-s1": {"spec": FlowSpec(
                "r2-s1", 1, 11, 100, 0, "KV_MOVEMENT", "P2D",
                request_ids=(2,))},
            "r3-s0": {"spec": FlowSpec(
                "r3-s0", 4, 8, 100, 0, "KV_MOVEMENT", "P2D",
                request_ids=(3,))},
            "r3-s1": {"spec": FlowSpec(
                "r3-s1", 5, 9, 100, 0, "KV_MOVEMENT", "P2D",
                request_ids=(3,))},
        }
        shared_cut = (12, 13)
        paths = {flow_id: [shared_cut] for flow_id in active}

        rates = network._rates(active, paths)

        self.assertAlmostEqual(rates["r3-s0"], 12.5e9)
        self.assertAlmostEqual(rates["r3-s1"], 12.5e9)
        self.assertEqual(rates["r2-s0"], 0.0)
        self.assertEqual(rates["r2-s1"], 0.0)
        self.assertAlmostEqual(sum(rates.values()), 25e9)

    def test_request_id_is_required_for_policy(self):
        with self.assertRaisesRegex(ValueError, "requires a concrete"):
            PersistentFluidFlowNetwork(
                TOPOLOGY, policy="KV_REQUEST_FIRST")

    def test_decode_collectives_remain_above_selected_request_kv(self):
        network = PersistentFluidFlowNetwork(
            TOPOLOGY, policy="EP_THEN_KV_REQUEST_FIRST",
            request_first_id=3)
        active = {
            "decode-ep": {"spec": FlowSpec(
                "decode-ep", 0, 1, 100, 0, "EP", "EP_DISPATCH",
                request_ids=(10,))},
            "selected-kv": {"spec": FlowSpec(
                "selected-kv", 2, 3, 100, 0, "KV_MOVEMENT", "P2D",
                request_ids=(3,))},
            "other-kv": {"spec": FlowSpec(
                "other-kv", 4, 5, 100, 0, "KV_MOVEMENT", "P2D",
                request_ids=(2,))},
        }
        shared_cut = (12, 13)
        paths = {flow_id: [shared_cut] for flow_id in active}

        rates = network._rates(active, paths)
        self.assertAlmostEqual(rates["decode-ep"], 25e9)
        self.assertEqual(rates["selected-kv"], 0.0)
        self.assertEqual(rates["other-kv"], 0.0)

        # Once the Decode collective drains, the selected request receives
        # the next service tier without changing the bytes or topology.
        rates = network._rates(
            {key: value for key, value in active.items()
             if key != "decode-ep"},
            {key: value for key, value in paths.items()
             if key != "decode-ep"})
        self.assertAlmostEqual(rates["selected-kv"], 25e9)
        self.assertEqual(rates["other-kv"], 0.0)


if __name__ == "__main__":
    unittest.main()
