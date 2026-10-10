#!/usr/bin/env python3
"""Plot a real communication timeline, or refuse if timestamps are absent."""

import argparse
import csv
from pathlib import Path

from semantic_events import is_study_communication


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("timeline", type=Path,
                        help="CSV with numeric start/end columns from an instrumented backend")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--include-compute", action="store_true",
                        help="also draw workload compute intervals")
    args = parser.parse_args()
    with args.timeline.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    timed = []
    for row in rows:
        try:
            start = float(row["start"])
            end = float(row["end"])
        except (KeyError, TypeError, ValueError):
            continue
        event_type = row.get("event_type", "event")
        is_compute = event_type in {"PREFILL_COMPUTE", "DECODE_COMPUTE"}
        if (not is_compute and not is_study_communication(row)):
            continue
        if end >= start and (args.include_compute or not is_compute):
            timed.append((start, end, row.get("event_type", "event")))
    if not timed:
        raise SystemExit(
            "No numeric event windows found; refusing to fabricate overlap. "
            "The current trace-text audit is graph order only."
        )
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise SystemExit("matplotlib is required for plotting an instrumented timeline") from exc
    output = args.output or args.timeline.with_suffix(".png")
    labels = sorted({event for _, _, event in timed})
    y = {label: index for index, label in enumerate(labels)}
    shown = set()
    for start, end, event in timed:
        label = event if event not in shown else None
        shown.add(event)
        plt.plot([start, end], [y[event], y[event]], linewidth=4, label=label)
    plt.yticks(range(len(labels)), labels)
    plt.xlabel("simulated time")
    plt.legend(loc="upper right")
    plt.tight_layout()
    plt.savefig(output, dpi=160)
    plt.close()
    print("wrote", output)


if __name__ == "__main__":
    main()
