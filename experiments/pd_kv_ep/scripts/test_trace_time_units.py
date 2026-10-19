#!/usr/bin/env python3
"""Nanosecond serving traces must become microsecond Chakra ET durations."""

import unittest

from serving.core.trace_generator import indexed_cols


class TraceTimeUnitTest(unittest.TestCase):
    def test_ns_duration_rounds_up_at_chakra_boundary(self):
        rows = [
            ("qkv_proj", "12345", "LOCAL", "1", "LOCAL", "0",
             "LOCAL", "2", "NONE", "0", "NONE"),
            ("o_proj", "1000", "LOCAL", "1", "LOCAL", "0",
             "LOCAL", "2", "NONE", "0", "NONE"),
            ("sampler", "1", "LOCAL", "1", "LOCAL", "0",
             "LOCAL", "2", "NONE", "0", "NONE"),
        ]

        converted = indexed_cols(rows)

        self.assertEqual([row[1] for row in converted], ["13", "1", "1"])
        self.assertEqual([row[0] for row in converted],
                         ["qkv_proj_0", "o_proj_1", "sampler_2"])

    def test_expert_markers_are_not_treated_as_timed_rows(self):
        self.assertEqual(indexed_cols([("EXPERT 0",)]), [["EXPERT", "0"]])


if __name__ == "__main__":
    unittest.main()
