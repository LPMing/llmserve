"""EP1 experts execute on every TP replica in common and P/D prefill graphs."""

import tempfile
import unittest
from pathlib import Path

from chakra.src.converter.llm_converter import LLMConverter
from serving.core.flowsim_worker import _read_graph


class MoEEP1TPReplicationTest(unittest.TestCase):
    def test_ep1_expert_is_on_both_tp_ranks(self):
        rows = [
            ["embedding_0", "100", "REMOTE:0", "4", "LOCAL", "4",
             "LOCAL", "4", "NONE", "0", "NONE"],
            ["EXPERT", "0", "NONE", "0"],
            ["expert_1", "900", "LOCAL", "4", "LOCAL", "4",
             "LOCAL", "4", "NONE", "0", "NONE"],
            ["EXPERT", "END", "NONE", "0"],
            ["sampler_2", "100", "LOCAL", "4", "LOCAL", "0",
             "REMOTE:0", "4", "NONE", "0", "NONE"],
        ]
        for mode in ("COLOCATED", "PREFILL"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                prefix = str(Path(folder) / "llm")
                converter = LLMConverter("test", prefix, 2)
                converter.convert_rows(
                    "%s model_parallel_NPU_group: 1" % mode, rows)
                for rank in (0, 1):
                    _, nodes = _read_graph("%s.%d.et" % (prefix, rank))
                    names = [node.name for node in nodes]
                    self.assertIn("COMP_NODE_expert_1", names,
                                  "expert missing from TP rank %d" % rank)
                    expert = next(node for node in nodes
                                  if node.name == "COMP_NODE_expert_1")
                    self.assertEqual(expert.duration_micros, 900)
                    sampler = next(node for node in nodes
                                   if node.name == "COMP_NODE_sampler_2")
                    self.assertIn(expert.id, sampler.data_deps)

    def test_ep2_experts_remain_sharded(self):
        rows = [
            ["embedding_0", "100", "REMOTE:0", "4", "LOCAL", "4",
             "LOCAL", "4", "NONE", "0", "NONE"],
            ["EXPERT", "0", "ALLGATHER", "4"],
            ["expert_0", "900", "LOCAL", "4", "LOCAL", "4",
             "LOCAL", "4", "NONE", "0", "NONE"],
            ["EXPERT", "1", "NONE", "0"],
            ["expert_1", "900", "LOCAL", "4", "LOCAL", "4",
             "LOCAL", "4", "NONE", "0", "NONE"],
            ["EXPERT", "END", "REDUCESCATTER", "4"],
            ["sampler_2", "100", "LOCAL", "4", "LOCAL", "0",
             "REMOTE:0", "4", "NONE", "0", "NONE"],
        ]
        with tempfile.TemporaryDirectory() as folder:
            prefix = str(Path(folder) / "llm")
            LLMConverter("test", prefix, 2).convert_rows(
                "COLOCATED model_parallel_NPU_group: 1", rows)
            for rank in (0, 1):
                _, nodes = _read_graph("%s.%d.et" % (prefix, rank))
                names = {node.name for node in nodes}
                self.assertIn("COMP_NODE_expert_%d" % rank, names)
                self.assertNotIn("COMP_NODE_expert_%d" % (1 - rank), names)


if __name__ == "__main__":
    unittest.main()
