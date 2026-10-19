#!/usr/bin/env python3
"""Regression tests for cluster-rank versus ASTRA-topology consistency."""

import unittest
import json
from pathlib import Path

from serving.core.config_builder import (
    _compute_network_dims,
    _resolve_dp_groups,
    _validate_network_rank_count,
)


def _instance(pd_type, num_npus, tp_size, dp_group=None):
    return {
        "pd_type": pd_type,
        "num_npus": num_npus,
        "tp_size": tp_size,
        "pp_size": 1,
        "ep_size": tp_size,
        "dp_group": dp_group,
        "is_moe": True,
    }


class NetworkRankCountTest(unittest.TestCase):
    def test_equal_tp_pd_layout_has_exact_rank_count(self):
        instances = [
            _instance("prefill", num_npus=2, tp_size=2),
            _instance("decode", num_npus=2, tp_size=2),
        ]
        self.assertEqual(_validate_network_rank_count(instances), [2, 3])

    def test_unequal_tp_pd_layout_fails_instead_of_hanging(self):
        instances = [
            _instance("prefill", num_npus=1, tp_size=1),
            _instance("decode", num_npus=2, tp_size=2),
        ]
        with self.assertRaisesRegex(ValueError, "configured serving ranks=4"):
            _validate_network_rank_count(instances)

    def test_prefill_plus_decode_dp_group_uses_separate_role_axis(self):
        instances = [
            _instance("prefill", num_npus=2, tp_size=2),
            _instance("decode", num_npus=2, tp_size=2, dp_group="decode"),
            _instance("decode", num_npus=2, tp_size=2, dp_group="decode"),
        ]
        for instance in instances[1:]:
            instance["ep_size"] = 4
        _resolve_dp_groups(instances)
        self.assertEqual(_validate_network_rank_count(instances), [2, 2, 2])
        self.assertEqual(instances[1]["ep_dim"], [True, True, False])

    def test_multiple_prefill_lanes_plus_one_ep_group_keep_all_ranks(self):
        instances = [
            _instance("prefill", num_npus=2, tp_size=2)
            for _ in range(2)
        ]
        for _ in range(2):
            instances.append(_instance(
                "decode", num_npus=2, tp_size=2, dp_group="decode"))
            instances[-1]["ep_size"] = 4

        _resolve_dp_groups(instances)
        self.assertEqual(_validate_network_rank_count(instances), [2, 2, 3])
        self.assertEqual(instances[2]["ep_dim"], [True, True, False])

    def test_saved_minimal_ep16_fixture_has_32_logical_rank_coordinates(self):
        repo_root = Path(__file__).resolve().parents[3]
        config_path = (repo_root / "experiments/pd_kv_ep/configs/large_scale/"
                       "minimal_1p2d_ep16_shared_400g.json")
        config = json.loads(config_path.read_text(encoding="utf-8"))
        instances = []
        for node in config["nodes"]:
            for entry in node["instances"]:
                instance = dict(entry)
                instance.update(pp_size=1, is_moe=True)
                instances.append(instance)

        _resolve_dp_groups(instances)
        physical_gpu_ranks = sum(item["num_npus"] for item in instances)
        legacy_frontend_ranks = sum(
            item["num_npus"] * (2 if item["pd_type"] == "prefill" else 1)
            for item in instances
        )
        self.assertEqual(physical_gpu_ranks, 24)
        self.assertEqual(legacy_frontend_ranks, 32)
        self.assertEqual(_compute_network_dims(instances), [2, 8, 2])
        self.assertEqual(_validate_network_rank_count(instances), [2, 8, 2])
        self.assertEqual(instances[8]["ep_dim"], [True, True, False])

    def test_two_independent_ep_groups_get_separate_outer_lanes(self):
        # Two legal EP8 groups each span four TP2 instances.  The P/D prefix
        # occupies two lanes; each contiguous EP group gets one separate lane.
        instances = [
            _instance("prefill", num_npus=2, tp_size=2)
            for _ in range(4)
        ]
        for group in ("ep_a", "ep_b"):
            group_instances = [
                _instance("decode", num_npus=2, tp_size=2,
                          dp_group=group)
                for _ in range(4)
            ]
            for instance in group_instances:
                instance["ep_size"] = 8
            instances.extend(group_instances)

        _resolve_dp_groups(instances)
        self.assertEqual(_compute_network_dims(instances), [2, 4, 4])
        self.assertEqual(_validate_network_rank_count(instances), [2, 4, 4])
        self.assertEqual(instances[4]["ep_dim"], [True, True, False])
        self.assertEqual(instances[8]["ep_dim"], [True, True, False])

        from serving.core.flowsim_worker import _collective_participants
        dims = (2, 4, 4)
        all_ranks = tuple(range(32))
        group_a = _collective_participants(
            16, all_ranks, tuple(instances[4]["ep_dim"]), dims)
        group_b = _collective_participants(
            24, all_ranks, tuple(instances[8]["ep_dim"]), dims)
        self.assertEqual(group_a, tuple(range(16, 24)))
        self.assertEqual(group_b, tuple(range(24, 32)))

    def test_multiple_decode_groups_without_prefill_have_outer_group_axis(self):
        instances = []
        for group in ("ep_a", "ep_b"):
            for _ in range(2):
                instances.append(_instance(
                    "decode", num_npus=2, tp_size=2,
                    dp_group=group))
                instances[-1]["ep_size"] = 4

        _resolve_dp_groups(instances)
        self.assertEqual(_compute_network_dims(instances), [2, 2, 2])
        self.assertEqual(instances[0]["ep_dim"], [True, True, False])
        self.assertEqual(instances[2]["ep_dim"], [True, True, False])

    def test_interleaved_independent_groups_fail_closed(self):
        instances = [
            _instance("decode", num_npus=2, tp_size=2,
                      dp_group=group)
            for group in ("ep_a", "ep_b", "ep_a", "ep_b")
        ]
        for instance in instances:
            instance["ep_size"] = 4

        with self.assertRaisesRegex(ValueError, "group-major instance order"):
            _resolve_dp_groups(instances)


if __name__ == "__main__":
    unittest.main()
