"""Keep malformed source timestamps out of ordered SwissAI analysis."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mine_swissai import partition_by_day, timestamp_ms


class SwissAITimestampTest(unittest.TestCase):
    def test_null_marker_and_invalid_timestamp(self):
        self.assertIsNone(timestamp_ms("\\N"))
        self.assertIsNone(timestamp_ms("invalid"))
        self.assertIsNone(timestamp_ms(None))
        self.assertEqual(timestamp_ms("2025-08-21T19:19:22.469Z"),
                         1755803962469)

    def test_partition_counts_bad_arrival_without_dropping_source_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            raw = directory / "input.jsonl"
            rows = [
                {"created_at": "\\N", "token_count": 16,
                 "bucket_ids": ["a"], "reported_token_input": 16},
                {"created_at": "2025-08-21T19:19:22.469Z",
                 "token_count": 16, "bucket_ids": ["a"],
                 "reported_token_input": 16},
            ]
            raw.write_text("".join(json.dumps(row) + "\n" for row in rows))
            days, _, _, differences, counts = partition_by_day(directory, raw)
            self.assertEqual(counts["source_rows"], 2)
            self.assertEqual(counts["invalid_created_at"], 1)
            self.assertEqual(counts["rows"], 1)
            self.assertEqual(days["2025-08-21"], 1)
            self.assertEqual(differences["0"], 1)
            json.dumps(differences, sort_keys=True)


if __name__ == "__main__":
    unittest.main()
