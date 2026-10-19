#!/usr/bin/env python3
"""Regression tests for Chakra collective round and communicator identity."""

import unittest

from serving.core.flowsim_worker import (
    _collective_identity,
    _collective_instance_key,
    _collective_participants,
    _rank_coordinates,
)


class _ValueAttr:
    def __init__(self, name, field, value):
        self.name = name
        self._field = field
        setattr(self, field, value)

    def WhichOneof(self, _):
        return self._field


class _BoolList:
    def __init__(self, values):
        self.values = values


class _CollectiveNode:
    def __init__(self, name, comm_type, involved_dim):
        self.name = name
        self.attr = [
            _ValueAttr("comm_type", "int64_val", comm_type),
            _ValueAttr("involved_dim", "bool_list",
                       _BoolList(involved_dim)),
        ]


class FlowSimCollectiveScopeTest(unittest.TestCase):
    dims = (2, 8, 2)
    decode_ranks = tuple(range(16, 32))

    def test_rank_coordinates_match_first_axis_fastest_astra_layout(self):
        self.assertEqual(_rank_coordinates(16, self.dims), (0, 0, 1))
        self.assertEqual(_rank_coordinates(17, self.dims), (1, 0, 1))
        self.assertEqual(_rank_coordinates(18, self.dims), (0, 1, 1))
        self.assertEqual(_rank_coordinates(31, self.dims), (1, 7, 1))

    def test_tp_collective_is_scoped_per_decode_instance(self):
        node = _CollectiveNode("tp_allreduce", 0, (True, False, False))
        key0 = _collective_instance_key(node, 16, 0, self.dims)[0]
        key1 = _collective_instance_key(node, 17, 0, self.dims)[0]
        key2 = _collective_instance_key(node, 18, 0, self.dims)[0]
        self.assertEqual(key0, key1)
        self.assertNotEqual(key0, key2)
        self.assertEqual(
            _collective_participants(16, self.decode_ranks,
                                     (True, False, False), self.dims),
            (16, 17))

    def test_ep_collective_spans_tp_and_decode_dp_but_not_role_axis(self):
        node = _CollectiveNode("expert_allgather", 2,
                               (True, True, False))
        key0 = _collective_instance_key(node, 16, 0, self.dims)[0]
        key1 = _collective_instance_key(node, 31, 0, self.dims)[0]
        prefill_key = _collective_instance_key(node, 0, 0, self.dims)[0]
        self.assertEqual(key0, key1)
        self.assertNotEqual(key0, prefill_key)
        self.assertEqual(
            _collective_participants(16, self.decode_ranks,
                                     (True, True, False), self.dims),
            self.decode_ranks)

    def test_repeated_layer_collectives_get_distinct_round_keys(self):
        node = _CollectiveNode("expert_allgather", 2,
                               (True, True, False))
        identity, _ = _collective_identity(node, self.dims)
        first = _collective_instance_key(node, 16, 0, self.dims)[0]
        second = _collective_instance_key(node, 16, 1, self.dims)[0]
        self.assertEqual(identity,
                         _collective_identity(node, self.dims)[0])
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
