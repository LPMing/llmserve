#!/usr/bin/env python3
"""Mine measured subagent forks and request shapes from raw FreeInference traces."""

import csv
import hashlib
import io
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import zstandard


HERE = Path(__file__).resolve().parent
RAW = HERE / "freeinference_raw"
MANIFEST = HERE / "freeinference_manifest.json"
OUTPUT = HERE / "freeinference_analysis"


def quantile(values, fraction):
    values = sorted(values)
    if not values:
        return None
    position = (len(values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def common_prefix_length(sequences):
    if not sequences:
        return 0
    limit = min(map(len, sequences))
    first = sequences[0]
    for index in range(limit):
        value = first[index]
        if any(other[index] != value for other in sequences[1:]):
            return index
    return limit


def max_concurrent(intervals):
    changes = []
    for start, end in intervals:
        if start is None or end is None or end < start:
            continue
        changes.extend(((start, 1), (end, -1)))
    active = maximum = 0
    for _, delta in sorted(changes):
        active += delta
        maximum = max(maximum, active)
    return maximum


def request_tokens(request):
    values = request.get("provider_tokens") or {}
    return int(values.get("prompt") or 0), int(values.get("completion") or 0)


def analyze_session(session, week, depth, counters, shapes, groups,
                    overlap_groups):
    counters["sessions_total"] += 1
    counters["sessions_nested" if depth else "sessions_root"] += 1
    counters["max_depth"] = max(counters["max_depth"], depth)
    requests = session.get("requests") or []
    session_children = []
    for index, request in enumerate(requests):
        counters["requests_total"] += 1
        counters["model:" + str(request.get("model"))] += 1
        ttft = request.get("ttft_ms")
        if ttft is not None and float(ttft) >= 0:
            shapes["provider_ttft_ms"].append(float(ttft))
        if request.get("start_ms") is not None and request.get("end_ms") is not None:
            duration = int(request["end_ms"]) - int(request["start_ms"])
            if duration >= 0:
                shapes["request_duration_ms"].append(duration)
        if index + 1 < len(requests):
            next_start = requests[index + 1].get("start_ms")
            this_end = request.get("end_ms")
            if next_start is not None and this_end is not None:
                gap = int(next_start) - int(this_end)
                if gap > 0:
                    shapes["positive_inter_request_gap_ms"].append(gap)
                    counters["positive_inter_request_gaps"] += 1
        prompt, completion = request_tokens(request)
        if prompt:
            shapes["prompt_tokens"].append(prompt)
            if prompt <= 2048:
                counters["requests_prompt_le_2048"] += 1
            if prompt >= 8192 and completion <= 128:
                counters["requests_long_context_short_output"] += 1
        if completion:
            shapes["completion_tokens"].append(completion)
        tools = request.get("tool_calls") or []
        counters["tool_calls_total"] += len(tools)
        children = [tool["subagent"] for tool in tools
                    if isinstance(tool.get("subagent"), dict)]
        session_children.extend((index, child) for child in children)
        counters["subagent_calls_total"] += len(children)
        if children:
            counters["parent_requests_with_subagent"] += 1
        if len(children) >= 2:
            starts = [int(child.get("start_ms") or 0) for child in children]
            ends = [int(child.get("end_ms") or 0) for child in children]
            first_requests = [(child.get("requests") or [None])[0]
                              for child in children]
            valid_first = [item for item in first_requests if item is not None]
            sibling_blocks = [item.get("block_ids") or []
                              for item in valid_first]
            common_blocks = (common_prefix_length(sibling_blocks)
                             if len(valid_first) == len(children) else 0)
            parent_blocks = request.get("block_ids") or []
            parent_common_blocks = common_prefix_length(
                [parent_blocks] + sibling_blocks) if sibling_blocks else 0
            branch_output = [sum(request_tokens(item)[1]
                                 for item in child.get("requests") or [])
                             for child in children]
            branch_prompt = [request_tokens(item)[0]
                             if item is not None else 0
                             for item in first_requests]
            first_ttft = [float(item["ttft_ms"]) for item in valid_first
                          if item.get("ttft_ms") is not None and
                          float(item["ttft_ms"]) >= 0]
            mean_output = sum(branch_output) / len(branch_output)
            output_cv = (math.sqrt(sum((value - mean_output) ** 2
                                       for value in branch_output) /
                                   len(branch_output)) / mean_output
                         if mean_output else 0.0)
            next_request = (requests[index + 1]
                            if index + 1 < len(requests) else None)
            next_start = (int(next_request["start_ms"])
                          if next_request is not None and
                          next_request.get("start_ms") is not None else None)
            group = {
                "week": week,
                "root_or_nested": "root" if depth == 0 else "nested",
                "parent_session_id": session.get("session_id"),
                "parent_step": request.get("step"),
                "parent_model": request.get("model"),
                "width": len(children),
                "child_start_skew_ms": max(starts) - min(starts),
                "child_end_skew_ms": max(ends) - min(ends),
                "child_duration_min_ms": min(end - start for start, end
                                             in zip(starts, ends)),
                "child_duration_max_ms": max(end - start for start, end
                                             in zip(starts, ends)),
                "group_span_ms": max(ends) - min(starts),
                "max_concurrent_children": max_concurrent(zip(starts, ends)),
                "shared_prefix_blocks": common_blocks,
                "shared_prefix_tokens_lower_bound": 16 * common_blocks,
                "parent_child_common_blocks": parent_common_blocks,
                "first_child_prompt_min": min(branch_prompt),
                "first_child_prompt_max": max(branch_prompt),
                "first_child_ttft_min_ms": min(first_ttft) if first_ttft else None,
                "first_child_ttft_max_ms": max(first_ttft) if first_ttft else None,
                "first_child_models": "|".join(sorted({
                    str(item.get("model")) for item in valid_first})),
                "branch_output_min": min(branch_output),
                "branch_output_max": max(branch_output),
                "branch_output_cv": round(output_cv, 6),
                "branch_request_count_min": min(
                    len(child.get("requests") or []) for child in children),
                "branch_request_count_max": max(
                    len(child.get("requests") or []) for child in children),
                "next_parent_request_start_ms": next_start,
                "last_child_end_ms": max(ends),
                "parent_join_lag_ms": (next_start - max(ends)
                                       if next_start is not None else None),
                "child_models_identical": len({
                    item.get("model") for item in valid_first}) == 1,
            }
            groups.append(group)
            counters["fork_groups_total"] += 1
            if group["max_concurrent_children"] >= 2:
                counters["fork_groups_overlapping"] += 1
            if group["shared_prefix_tokens_lower_bound"] >= 256:
                counters["fork_groups_shared_prefix_ge_256"] += 1
        for child in children:
            analyze_session(child, week, depth + 1, counters, shapes, groups,
                            overlap_groups)
    valid_children = sorted(
        ((int(child["start_ms"]), int(child["end_ms"]), index, child)
         for index, child in session_children
         if child.get("start_ms") is not None and
         child.get("end_ms") is not None and
         int(child["end_ms"]) >= int(child["start_ms"])),
        key=lambda item: item[0])
    components = []
    for item in valid_children:
        if components and item[0] < max(child[1] for child in components[-1]):
            components[-1].append(item)
        else:
            components.append([item])
    for component in components:
        if len(component) < 2:
            continue
        first_requests = [(item[3].get("requests") or [None])[0]
                          for item in component]
        blocks = [(request.get("block_ids") or []) if request else []
                  for request in first_requests]
        prompt = [request_tokens(request)[0] if request else 0
                  for request in first_requests]
        origin_steps = len({item[2] for item in component})
        overlap_groups.append({
            "week": week,
            "parent_session_id": session.get("session_id"),
            "root_or_nested": "root" if depth == 0 else "nested",
            "width": len(component),
            "parent_request_count": origin_steps,
            "max_concurrent_children": max_concurrent(
                (item[0], item[1]) for item in component),
            "shared_prefix_blocks": common_prefix_length(blocks),
            "shared_prefix_tokens_lower_bound": 16 * common_prefix_length(blocks),
            "first_child_prompt_min": min(prompt),
            "first_child_prompt_max": max(prompt),
            "first_child_model_count": len({request.get("model")
                                             for request in first_requests
                                             if request}),
            "first_start_ms": component[0][0],
            "last_end_ms": max(item[1] for item in component),
        })
        counters["overlap_components_total"] += 1
        if origin_steps >= 2:
            counters["overlap_components_cross_request"] += 1
        if common_prefix_length(blocks) >= 16:
            counters["overlap_components_shared_prefix_ge_256"] += 1


def main():
    manifest = json.loads(MANIFEST.read_text())
    OUTPUT.mkdir(exist_ok=True)
    counters = Counter()
    weekly = defaultdict(Counter)
    shapes = defaultdict(list)
    groups = []
    overlap_groups = []
    root_id_digests = {}
    for relative, file_info in sorted(manifest["files"].items()):
        path = RAW / relative
        if not path.exists():
            raise FileNotFoundError(path)
        if hashlib.sha256(path.read_bytes()).hexdigest() != file_info["sha256"]:
            raise ValueError("raw trace checksum mismatch: %s" % path)
        week = relative.split("/")[1]
        file_counts = Counter()
        with path.open("rb") as compressed:
            stream = zstandard.ZstdDecompressor().stream_reader(compressed)
            with io.TextIOWrapper(stream, encoding="utf-8") as lines:
                for line in lines:
                    root = json.loads(line)
                    root_id = root.get("session_id")
                    digest = hashlib.sha256(line.encode("utf-8")).hexdigest()
                    if root_id in root_id_digests:
                        if root_id_digests[root_id] != digest:
                            raise ValueError("duplicate root ID has different content")
                        file_counts["duplicate_root_rows"] += 1
                        continue
                    root_id_digests[root_id] = digest
                    analyze_session(root, week, 0, file_counts, shapes,
                                    groups, overlap_groups)
        depth = file_counts.pop("max_depth", 0)
        counters.update(file_counts)
        counters["max_depth"] = max(counters["max_depth"], depth)
        weekly[week].update(file_counts)
        weekly[week]["max_depth"] = max(weekly[week]["max_depth"], depth)
        file_counts["max_depth"] = depth
        print(relative, "roots", file_counts["sessions_root"],
              "requests", file_counts["requests_total"],
              "forks", file_counts["fork_groups_total"], flush=True)
    group_csv = OUTPUT / "fork_groups.csv"
    with group_csv.open("w", newline="") as stream:
        if groups:
            writer = csv.DictWriter(stream, fieldnames=list(groups[0]))
            writer.writeheader()
            writer.writerows(groups)
    overlap_csv = OUTPUT / "overlap_components.csv"
    with overlap_csv.open("w", newline="") as stream:
        if overlap_groups:
            writer = csv.DictWriter(stream, fieldnames=list(overlap_groups[0]))
            writer.writeheader()
            writer.writerows(overlap_groups)
    weekly_csv = OUTPUT / "weekly_counts.csv"
    keys = sorted(set().union(*(set(counts) for counts in weekly.values())))
    with weekly_csv.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["week"] + keys)
        writer.writeheader()
        for week, counts in sorted(weekly.items()):
            writer.writerow(dict(week=week, **counts))
    report = {
        "dataset": manifest["dataset"],
        "revision": manifest["revision"],
        "sampled_weeks": sorted(weekly),
        "sampled_raw_files": len(manifest["files"]),
        "counters": dict(counters),
        "prompt_tokens_p50_p95_p99": [
            quantile(shapes["prompt_tokens"], fraction)
            for fraction in (0.5, 0.95, 0.99)],
        "completion_tokens_p50_p95_p99": [
            quantile(shapes["completion_tokens"], fraction)
            for fraction in (0.5, 0.95, 0.99)],
        "positive_inter_request_gap_ms_p50_p95_p99": [
            quantile(shapes["positive_inter_request_gap_ms"], fraction)
            for fraction in (0.5, 0.95, 0.99)],
        "provider_ttft_ms_p50_p95_p99": [
            quantile(shapes["provider_ttft_ms"], fraction)
            for fraction in (0.5, 0.95, 0.99)],
        "request_duration_ms_p50_p95_p99": [
            quantile(shapes["request_duration_ms"], fraction)
            for fraction in (0.5, 0.95, 0.99)],
        "fork_width_p50_p95_max": [
            quantile([group["width"] for group in groups], fraction)
            for fraction in (0.5, 0.95, 1.0)],
        "fork_release_skew_ms_p50_p95": [
            quantile([group["child_start_skew_ms"] for group in groups], fraction)
            for fraction in (0.5, 0.95)],
        "fork_shared_prefix_tokens_p50_p95": [
            quantile([group["shared_prefix_tokens_lower_bound"]
                      for group in groups], fraction)
            for fraction in (0.5, 0.95)],
        "fork_with_overlap_and_shared_prefix_ge_256": sum(
            group["max_concurrent_children"] >= 2 and
            group["shared_prefix_tokens_lower_bound"] >= 256
            for group in groups),
        "fork_with_overlap_shared_prefix_256_and_profile_domain": sum(
            group["max_concurrent_children"] >= 2 and
            group["shared_prefix_tokens_lower_bound"] >= 256 and
            group["first_child_prompt_max"] <= 16384
            for group in groups),
        "fork_first_child_prompt_le_2048": sum(
            group["first_child_prompt_max"] <= 2048 for group in groups),
        "fork_first_child_prompt_le_16384": sum(
            group["first_child_prompt_max"] <= 16384 for group in groups),
        "overlap_cross_request_with_shared_prefix_ge_256": sum(
            group["parent_request_count"] >= 2 and
            group["shared_prefix_tokens_lower_bound"] >= 256
            for group in overlap_groups),
        "overlap_with_shared_prefix_256_and_profile_domain": sum(
            group["shared_prefix_tokens_lower_bound"] >= 256 and
            group["first_child_prompt_max"] <= 16384
            for group in overlap_groups),
        "group_csv_sha256": hashlib.sha256(group_csv.read_bytes()).hexdigest(),
        "overlap_csv_sha256": hashlib.sha256(
            overlap_csv.read_bytes()).hexdigest(),
    }
    (OUTPUT / "summary.json").write_text(json.dumps(report, indent=2,
                                                   sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
