"""Dependency-light regression for the skew timing aggregation contract."""

import ast
import unittest
from pathlib import Path
from types import SimpleNamespace


SOURCE = Path(__file__).resolve().parents[1] / "core/skew.py"


def load_measure():
    tree = ast.parse(SOURCE.read_text())
    node = next(item for item in tree.body
                if isinstance(item, ast.FunctionDef) and item.name == "_measure")

    class Shot:
        def __init__(self, requests):
            self.requests = requests

        def as_dict(self):
            return {"requests": self.requests}

    names = {"Shot": Shot,
             "TimingSample": lambda **fields: SimpleNamespace(**fields)}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), "exec"),
         names)
    return names["_measure"]


class _LLM:
    def __init__(self, samples):
        self.samples = samples

    def collective_rpc(self, method, args):
        assert method == "fire"
        assert args[2] == "attention"
        return [self.samples]


class SkewMeasureAverageTest(unittest.TestCase):
    def test_one_layer_cost_averages_multiple_attention_samples(self):
        measure = load_measure()
        samples = [{"layer": "attention", "microseconds": 2},
                   {"layer": "attention", "microseconds": 4},
                   {"layer": "attention", "microseconds": 6},
                   {"layer": "other", "microseconds": 100}]
        self.assertEqual(measure(_LLM(samples), [(1, 2048)], {}, 1), 4.0)

    def test_missing_attention_is_an_error(self):
        measure = load_measure()
        with self.assertRaisesRegex(RuntimeError, "no attention timing"):
            measure(_LLM([{"layer": "other", "microseconds": 10}]),
                    [(1, 2048)], {}, 1)


if __name__ == "__main__":
    unittest.main()
