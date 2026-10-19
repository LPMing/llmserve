"""Guard model-exact P2D byte units in the transfer-only stage."""

import unittest
from types import SimpleNamespace

from serving.core.trace_generator import generate_handoff_trace
from serving.core.utils import get_config


class TwoStageTraceTest(unittest.TestCase):
    def test_llama_14k_bf16_bytes(self):
        req = SimpleNamespace(
            original_input=14000,
            destination_prefix_reservation={"required_blocks": 876})
        batch = SimpleNamespace(handoff_only=True, requests=[req])
        trace = generate_handoff_trace(
            batch, get_config("meta-llama/Llama-3.1-8B"),
            tp_size=1, pp_size=1, fp=16,
            kv_cache_dtype="auto", path="/tmp/handoff.txt")
        self.assertEqual(int(trace.rows[1][9]), 1835008000)
        self.assertEqual(trace.rows[0][1], "0")
        self.assertEqual(trace.rows[1][1], "0")

    def test_fp8_is_half_bf16(self):
        req = SimpleNamespace(
            original_input=2048,
            destination_prefix_reservation={"required_blocks": 129})
        batch = SimpleNamespace(handoff_only=True, requests=[req])
        trace = generate_handoff_trace(
            batch, get_config("meta-llama/Llama-3.1-8B"),
            tp_size=1, pp_size=1, fp=16,
            kv_cache_dtype="fp8", path="/tmp/handoff.txt")
        self.assertEqual(int(trace.rows[1][9]), 134217728)

    def test_pinned_decode_prefix_sends_delta_only(self):
        req = SimpleNamespace(
            original_input=2048, destination_prefix_reuse_tokens=1984,
            destination_prefix_reservation={"required_blocks": 129})
        batch = SimpleNamespace(handoff_only=True, requests=[req])
        trace = generate_handoff_trace(
            batch, get_config("meta-llama/Llama-3.1-8B"),
            tp_size=1, pp_size=1, fp=16,
            kv_cache_dtype="auto", path="/tmp/handoff.txt")
        self.assertEqual(int(trace.rows[1][9]), 8388608)


if __name__ == "__main__":
    unittest.main()
