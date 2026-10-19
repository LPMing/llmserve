#!/usr/bin/env python3
"""Ensure packet runs honor the experiment topology and DCQCN template."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from serving.__main__ import (
    _prepare_ns3_config,
    _write_ns3_logical_topology,
)


class Ns3ConfigSelectionTest(unittest.TestCase):
    def test_custom_topology_template_and_outputs_are_used(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            astra = root / "astra-sim"
            template = root / "dcqcn.conf"
            inputs = root / "run-inputs"
            astra.mkdir()
            template.write_text(
                "TOPOLOGY_FILE default-topology.txt\n"
                "FLOW_FILE default-flow.txt\n"
                "TRACE_FILE default-trace.txt\n"
                "TRACE_OUTPUT_FILE default-trace.out\n"
                "FCT_OUTPUT_FILE default-fct.txt\n"
                "PFC_OUTPUT_FILE default-pfc.txt\n"
                "QLEN_MON_FILE default-queue.txt\n"
                "COMM_EVENTS_FILE default-events.csv\n"
                "CC_TELEMETRY_FILE default-cc.csv\n"
                "LOCAL_ECN_MARK_FILE default-ecn.csv\n"
                "LINK_TIMESERIES_FILE default-links.csv\n"
                "LINK_SUMMARY_FILE default-summary.csv\n"
                "CC_MODE 1\n", encoding="utf-8")

            generated = Path(_prepare_ns3_config(
                str(astra), SimpleNamespace(inputs_root=str(inputs)),
                topology_path="/topologies/pd-logical.txt",
                template_path=str(template)))
            contents = generated.read_text(encoding="utf-8")
            self.assertIn("TOPOLOGY_FILE /topologies/pd-logical.txt", contents)
            self.assertIn("CC_MODE 1", contents)
            self.assertIn(str(inputs / "ns3/output/flow.txt"), contents)
            self.assertIn(str(inputs / "ns3/output/comm_events.csv"), contents)
            self.assertNotIn("default-topology.txt", contents)
            self.assertNotIn("default-events.csv", contents)

            logical_topology = inputs / "ns3/logical_topology.json"
            _write_ns3_logical_topology(str(logical_topology), [2, 8, 2])
            self.assertEqual(
                logical_topology.read_text(encoding="utf-8"),
                '{"logical-dims": ["2", "8", "2"]}\n')


if __name__ == "__main__":
    unittest.main()
