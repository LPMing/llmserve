import unittest
from unittest.mock import Mock, patch

from serving.core.gate_function import GateRouter


class GateRouterProvenanceTests(unittest.TestCase):
    @patch("serving.core.gate_function.get_logger", return_value=Mock())
    def test_rr_uses_distinct_batch_token_ordinals_and_conserves_routes(self, _):
        router = GateRouter(
            node_id=0,
            instance_id=0,
            num_local_experts=8,
            num_experts_per_tok=2,
            routing_policy="RR",
        )

        result = router.route_ep(
            layer_num=7,
            batch_id="rr-regression",
            total_len=4,
            ep_size=4,
            capture_routes=True,
        )

        self.assertEqual(result.local_tokens, [2, 3, 1, 0])
        self.assertEqual(result.activated_experts, [2, 2, 1, 0])
        self.assertEqual(result.source_tokens, [1, 1, 1, 1])
        self.assertEqual(
            result.pair_matrix,
            [
                [1, 0, 0, 0],
                [1, 1, 0, 0],
                [0, 1, 0, 0],
                [0, 1, 1, 0],
            ],
        )
        self.assertEqual(
            [r["selected_expert_ids"] for r in result.token_routes],
            [[0, 1], [1, 2], [2, 3], [3, 4]],
        )
        self.assertEqual(
            [r["batch_token_ordinal"] for r in result.token_routes],
            [0, 1, 2, 3],
        )
        self.assertEqual(result.layer_num, 7)
        self.assertEqual(result.batch_id, "rr-regression")
        self.assertEqual(result.provenance, "SIMULATOR_POLICY_RR")

        for source, row in enumerate(result.pair_matrix):
            self.assertEqual(sum(row), len({
                owner
                for route in result.token_routes
                if route["source_rank"] == source
                for owner in route["destination_owner_ranks"]
            }))
        for route in result.token_routes:
            self.assertEqual(
                route["destination_owner_ranks"],
                sorted(set(route["selected_expert_owner_ranks"])),
            )

    @patch("serving.core.gate_function.get_logger", return_value=Mock())
    def test_balanced_is_explicitly_aggregate_not_fake_token_provenance(self, _):
        router = GateRouter(
            node_id=0,
            instance_id=0,
            num_local_experts=128,
            num_experts_per_tok=8,
            routing_policy="BALANCED",
        )

        result = router.route_ep(
            layer_num=0,
            batch_id="balanced-aggregate",
            total_len=64,
            ep_size=64,
            capture_routes=True,
        )

        # Qwen has 128 experts, so EP64 assigns two experts per rank.
        self.assertEqual(result.activated_experts, [2] * 64)
        self.assertEqual(result.provenance, "BALANCED_ANALYTIC_APPROXIMATION")
        self.assertIsNone(result.token_routes)
        self.assertIsNone(result.pair_matrix)
        self.assertIsNone(result.owner_expert_token_counts)

    @patch("serving.core.gate_function.get_logger", return_value=Mock())
    def test_seeded_rand_provenance_is_reproducible(self, _):
        def run_once():
            router = GateRouter(
                node_id=0,
                instance_id=0,
                num_local_experts=16,
                num_experts_per_tok=2,
                routing_policy="RAND",
                seed=123,
            )
            return router.route_ep(
                layer_num=2,
                batch_id="rand-regression",
                total_len=12,
                ep_size=4,
                capture_routes=True,
            )

        first, second = run_once(), run_once()
        self.assertEqual(first.token_routes, second.token_routes)
        self.assertEqual(first.pair_matrix, second.pair_matrix)
        self.assertEqual(first.local_tokens, second.local_tokens)
        self.assertEqual(sum(map(sum, first.pair_matrix)),
                         sum(first.local_tokens))


if __name__ == "__main__":
    unittest.main()
