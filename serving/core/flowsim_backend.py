"""Small Python 3 flow-level backend used by the serving frontend.

The public FlowSim prototype is an event-driven max-min flow simulator, but
the checked-out implementation is Python 2 oriented and its topology classes
do not consume the ns-3 topology format used by this repository.  This module
keeps the same useful abstraction (flows, directed paths, max-min sharing)
and deliberately adapts only the part needed by LLMServingSim.

This is a fluid flow model.  ``queue_bytes`` is residual fluid, not a packet
queue.  ECN, PFC, drops, and packet-level serialization are therefore not
reported as if they had been simulated.
"""

from dataclasses import dataclass
from collections import defaultdict, deque
import heapq
import math
import os
import re


_GBPS_RE = re.compile(r"^([0-9.]+)\s*Gbps$", re.IGNORECASE)
_MS_RE = re.compile(r"^([0-9.]+)\s*ms$", re.IGNORECASE)


@dataclass
class FlowSpec:
    flow_id: str
    src: int
    dst: int
    bytes: int
    start_ns: int
    traffic_class: str
    traffic_subtype: str
    # Serving provenance is observational only.  A flow can represent a
    # batch aggregate, so request_ids is deliberately a tuple rather than a
    # single request_id.  Consumers must not divide aggregate bytes unless
    # the tuple contains exactly one request.
    request_ids: tuple = ()
    batch_id: int = None
    collective_batch_id: int = None
    layer_id: int = None
    event_type: int = None
    collective_id: int = None
    collective_type: str = None
    # NIXL Push publication metadata. These are provenance/control fields;
    # bytes and timing still come from the fluid network.
    push_start_tokens: int = None
    push_end_tokens: int = None
    push_final: int = None
    push_epoch: int = None
    push_settled_tokens: int = None
    # Optional offline characterization route.  Production/integrated callers
    # leave this empty and use the backend route lookup.  P2 oracle replay may
    # supply one concrete shortest physical-pair path without changing bytes
    # or serving semantics; it is not an online routing policy.
    path_override: tuple = ()


class FluidFlowNetwork:
    """Directed, event-driven max-min flow model with simple priority modes."""

    def __init__(self, topology_path, policy="FAIR",
                 parallel_link_mode="AGGREGATE"):
        self.policy = str(policy).upper()
        self.parallel_link_mode = str(parallel_link_mode).upper()
        if self.parallel_link_mode not in ("AGGREGATE", "HASHED_PHYSICAL"):
            raise ValueError(
                "unsupported FlowSim parallel_link_mode %r" %
                self.parallel_link_mode)
        self.edges = {}
        self.physical_edges = {}
        self.adj = defaultdict(list)
        self._paths = {}
        self.topology_audit = {}
        self.telemetry = []
        self.last_flows = []
        # Per-event telemetry is useful for a small validation window, but it
        # is not part of the serving completion path.  Keep it bounded so a
        # trace with many short flow completions cannot retain an unbounded
        # Python object list.
        self.max_telemetry_rows = max(
            0, int(os.environ.get("FLOWSIM_MAX_TELEMETRY_ROWS", "4096")))
        # Large request-driven runs can produce several telemetry rows per
        # FlowSim event.  A small explicit link set lets characterization
        # runs retain a complete measurement window without storing every
        # endpoint attachment.  An empty value preserves legacy all-link
        # behavior.
        self.telemetry_link_ids = {
            value.strip()
            for value in os.environ.get(
                "FLOWSIM_TELEMETRY_LINK_IDS", "").split(",")
            if value.strip()
        }
        self.telemetry_start_ns = max(
            0, int(os.environ.get("FLOWSIM_TELEMETRY_START_NS", "0")))
        telemetry_end = os.environ.get("FLOWSIM_TELEMETRY_END_NS")
        self.telemetry_end_ns = (
            None if telemetry_end in (None, "") else int(telemetry_end))
        if (self.telemetry_end_ns is not None and
                self.telemetry_end_ns < self.telemetry_start_ns):
            raise ValueError(
                "FLOWSIM_TELEMETRY_END_NS precedes START_NS")
        self.telemetry_truncated = False
        self.telemetry_truncated_at_ns = None
        self._rate_debug_count = 0
        self._read_ns3_topology(topology_path)

    def _telemetry_in_window(self, timestamp_ns):
        timestamp_ns = int(timestamp_ns)
        return (timestamp_ns >= self.telemetry_start_ns and
                (self.telemetry_end_ns is None or
                 timestamp_ns <= self.telemetry_end_ns))

    def _telemetry_link_enabled(self, link):
        return (not self.telemetry_link_ids or
                self._link_name(link) in self.telemetry_link_ids)

    def _append_link_telemetry(self, active, paths, rates, link_rates,
                               link_outstanding, interval_start_ns,
                               interval_end_ns):
        """Record interval-scoped allocation and demand proxies.

        FlowSpec has a byte count and release time, but no finite source-rate
        cap.  Consequently the backend has no exact unconstrained offered
        rate or rho.  These fields expose allocated rates, active-flow counts,
        and newly released bytes without presenting them as offered load.
        ``queue_bytes`` is retained for compatibility; it is the sum of
        remaining fluid bytes on paths using a link, not a switch queue.
        """
        if (not self.max_telemetry_rows or
                not self._telemetry_in_window(interval_end_ns)):
            return

        per_link = {}
        for flow_id, data in active.items():
            spec = data["spec"]
            traffic_class = str(spec.traffic_class or "OTHER").upper()
            rate = float(rates.get(flow_id, 0.0))
            started_here = int(data.get("start_ns", -1)) == int(interval_start_ns)
            for link in paths[flow_id]:
                if link not in link_rates or not self._telemetry_link_enabled(link):
                    continue
                entry = per_link.setdefault(link, {
                    "active_flows": 0,
                    "allocated_rate_Bps": 0.0,
                    "active_by_class": defaultdict(int),
                    "rate_by_class": defaultdict(float),
                    "released_by_class": defaultdict(int),
                })
                entry["active_flows"] += 1
                entry["allocated_rate_Bps"] += rate
                entry["active_by_class"][traffic_class] += 1
                entry["rate_by_class"][traffic_class] += rate
                if started_here:
                    entry["released_by_class"][traffic_class] += int(spec.bytes)

        for link, entry in per_link.items():
            if len(self.telemetry) >= self.max_telemetry_rows:
                self.telemetry_truncated = True
                if self.telemetry_truncated_at_ns is None:
                    self.telemetry_truncated_at_ns = int(interval_end_ns)
                break
            capacity = float(self._edge(link)["capacity_Bps"])
            active_by_class = entry["active_by_class"]
            rate_by_class = entry["rate_by_class"]
            released_by_class = entry["released_by_class"]
            kv_rate = float(rate_by_class.get("KV_MOVEMENT", 0.0))
            ep_rate = float(rate_by_class.get("EP", 0.0))
            kv_count = int(active_by_class.get("KV_MOVEMENT", 0))
            ep_count = int(active_by_class.get("EP", 0))
            kv_released = int(released_by_class.get("KV_MOVEMENT", 0))
            ep_released = int(released_by_class.get("EP", 0))
            self.telemetry.append({
                "interval_start_ns": int(interval_start_ns),
                "timestamp_ns": int(interval_end_ns),
                "interval_duration_ns": max(
                    0, int(interval_end_ns) - int(interval_start_ns)),
                "link_id": self._link_name(link),
                "traffic_class": "MIXED",
                "active_flows": int(entry["active_flows"]),
                "active_kv_flows": kv_count,
                "active_ep_flows": ep_count,
                "allocated_rate_Bps": entry["allocated_rate_Bps"],
                "kv_allocated_rate_Bps": kv_rate,
                "ep_allocated_rate_Bps": ep_rate,
                "other_allocated_rate_Bps": max(
                    0.0, entry["allocated_rate_Bps"] - kv_rate - ep_rate),
                "released_bytes": kv_released + ep_released + int(
                    released_by_class.get("OTHER", 0)),
                "released_kv_bytes": kv_released,
                "released_ep_bytes": ep_released,
                "utilization": (
                    entry["allocated_rate_Bps"] / capacity
                    if capacity else 0.0),
                "queue_bytes": int(round(link_outstanding.get(link, 0.0))),
                "fluid_outstanding_bytes": int(
                    round(link_outstanding.get(link, 0.0))),
                "offered_rate_Bps": None,
                "offered_rho": None,
            })

    @staticmethod
    def _capacity(text):
        match = _GBPS_RE.match(text)
        if not match:
            raise ValueError("unsupported link capacity %r" % text)
        return float(match.group(1)) * 1_000_000_000.0 / 8.0

    @staticmethod
    def _latency(text):
        match = _MS_RE.match(text)
        if not match:
            raise ValueError("unsupported link latency %r" % text)
        return float(match.group(1)) * 1_000_000.0

    def _read_ns3_topology(self, path):
        if not path or not os.path.isfile(path):
            raise FileNotFoundError("FlowSim topology does not exist: %s" % path)
        with open(path, "r", encoding="utf-8") as stream:
            lines = [line.strip() for line in stream if line.strip() and not line.lstrip().startswith("#")]
        if not lines:
            raise ValueError("FlowSim topology is empty: %s" % path)

        header = lines[0].split()
        if len(header) < 3 or not all(item.lstrip("-").isdigit() for item in header[:3]):
            raise ValueError("invalid ns-3 topology header in %s" % path)
        declared_nodes, declared_switches, declared_edges = map(int, header[:3])
        switch_nodes = set()
        edge_start = 1
        # Topology generators use either one switch-ID line or several lines.
        # Consume numeric switch-ID lines until the first line whose third
        # field is a link-rate token; otherwise a split switch list can make a
        # switch look like an endpoint in the audit.
        while edge_start < len(lines) and len(switch_nodes) < declared_switches:
            fields = lines[edge_start].split()
            if len(fields) >= 4 and _GBPS_RE.match(fields[2]):
                break
            switch_nodes.update(
                int(item) for item in fields
                if item.lstrip("-").isdigit())
            edge_start += 1

        # The ns-3 files used by this repository list each physical point-to-
        # point link once.  A Clos leaf-to-spine pair can consequently occur
        # many times.  Do not store those records directly in ``edges[(src,
        # dst)]``: doing so silently replaced (for example) sixteen 200-Gbps
        # links with one 200-Gbps link.  FlowSim has one fluid resource per
        # directed endpoint pair, so identical parallel links are represented
        # by their exactly equivalent aggregate capacity.  The physical count
        # is retained in the edge metadata and in the topology audit.
        listed = defaultdict(list)
        for line in lines[edge_start:]:
            fields = line.split()
            if len(fields) < 4 or not fields[0].lstrip("-").isdigit():
                continue
            src, dst = int(fields[0]), int(fields[1])
            link = {
                "capacity_Bps": self._capacity(fields[2]),
                "latency_ns": self._latency(fields[3]),
            }
            listed[(src, dst)].append(link)

        # Materialize reverse directions only when the input did not already
        # provide that direction.  This preserves the historical topology
        # file convention while retaining every parallel record.
        directed = defaultdict(list)
        for pair, links in listed.items():
            directed[pair].extend(links)
        for (src, dst), links in listed.items():
            if (dst, src) not in listed:
                directed[(dst, src)].extend(dict(link) for link in links)

        physical_edge_count = sum(len(links) for links in listed.values())
        reverse_materialized_count = sum(
            len(links) for pair, links in directed.items()
            if pair not in listed)

        for (src, dst), links in directed.items():
            latencies = {link["latency_ns"] for link in links}
            if len(latencies) != 1:
                raise ValueError(
                    "FlowSim cannot aggregate parallel links with different "
                    "latencies for %d->%d: %s" %
                    (src, dst, sorted(latencies)))
            capacity = sum(link["capacity_Bps"] for link in links)
            self.edges[(src, dst)] = {
                "capacity_Bps": capacity,
                "latency_ns": next(iter(latencies)),
                "physical_link_count": len(links),
                "physical_capacity_Bps": tuple(
                    link["capacity_Bps"] for link in links),
            }
            for index, link in enumerate(links):
                self.physical_edges[(src, dst, index)] = {
                    "capacity_Bps": link["capacity_Bps"],
                    "latency_ns": link["latency_ns"],
                    "aggregate_pair": (src, dst),
                    "physical_index": index,
                }
            if dst not in self.adj[src]:
                self.adj[src].append(dst)

        if not self.edges:
            raise ValueError("FlowSim could not find directed links in %s" % path)

        endpoint_nodes = set(range(declared_nodes)) - switch_nodes
        self.topology_audit = {
            "topology_path": os.path.abspath(path),
            "declared_node_count": declared_nodes,
            "declared_switch_count": declared_switches,
            "declared_physical_edge_count": declared_edges,
            "parsed_physical_edge_count": physical_edge_count,
            "reverse_materialized_physical_edge_count": reverse_materialized_count,
            "directed_physical_edge_count": sum(
                item["physical_link_count"] for item in self.edges.values()),
            "directed_aggregate_pair_count": len(self.edges),
            "switch_nodes": sorted(switch_nodes),
            "endpoint_nodes": sorted(endpoint_nodes),
            "parallel_pairs": [
                {
                    "src": src,
                    "dst": dst,
                    "physical_link_count": edge["physical_link_count"],
                    "aggregate_capacity_Bps": edge["capacity_Bps"],
                    "capacity_Bps_per_physical_link": list(
                        edge["physical_capacity_Bps"]),
                }
                for (src, dst), edge in sorted(self.edges.items())
                if edge["physical_link_count"] > 1
            ],
            "routing_model": "single_path_bfs_over_aggregate_directed_pairs",
            "parallel_link_model": (
                "strict_equivalent_capacity_aggregation"
                if self.parallel_link_mode == "AGGREGATE"
                else "deterministic_flow_hash_to_one_physical_parallel_link"),
            "parallel_link_mode": self.parallel_link_mode,
        }

    def _edge(self, link):
        """Return resource metadata for a logical or physical link."""
        if len(link) == 3:
            return self.physical_edges[link]
        return self.edges[link]

    @staticmethod
    def _link_name(link):
        if len(link) == 3:
            return "%d->%d#%d" % link
        return "%d->%d" % link

    @staticmethod
    def _physical_link_index(flow_id, pair, count):
        # This is a deterministic sensitivity model, not a packet ECMP
        # implementation.  A flow selects one physical resource in a bundle.
        import hashlib
        digest = hashlib.blake2b(
            (str(flow_id) + "|%d->%d" % pair).encode("utf-8"),
            digest_size=8).digest()
        return int.from_bytes(digest, byteorder="big") % count

    def _materialize_physical_path(self, logical_path, flow_id):
        if self.parallel_link_mode != "HASHED_PHYSICAL":
            return logical_path
        result = []
        for pair in logical_path:
            edge = self.edges[pair]
            count = int(edge["physical_link_count"])
            if count <= 1:
                result.append(pair)
            else:
                result.append((
                    pair[0], pair[1],
                    self._physical_link_index(flow_id, pair, count)))
        return result

    def path(self, src, dst):
        key = (int(src), int(dst))
        if key in self._paths:
            return self._paths[key]
        if src == dst:
            self._paths[key] = []
            return []
        parents = {int(src): None}
        queue = deque([int(src)])
        while queue:
            node = queue.popleft()
            for nxt in self.adj.get(node, ()):
                if nxt in parents:
                    continue
                parents[nxt] = node
                if nxt == int(dst):
                    queue.clear()
                    break
                queue.append(nxt)
        if int(dst) not in parents:
            raise ValueError("FlowSim has no directed path %d -> %d" % (src, dst))
        nodes = []
        node = int(dst)
        while node is not None:
            nodes.append(node)
            node = parents[node]
        nodes.reverse()
        links = list(zip(nodes, nodes[1:]))
        self._paths[key] = links
        return links

    def _resolve_flow_path(self, spec):
        if not spec.path_override:
            return self._materialize_physical_path(
                self.path(spec.src, spec.dst), spec.flow_id)
        path = [tuple(link) for link in spec.path_override]
        if not path or path[0][0] != int(spec.src) or path[-1][1] != int(spec.dst):
            raise ValueError(
                "FlowSim path_override endpoints do not match flow %s"
                % spec.flow_id)
        if self.parallel_link_mode == "HASHED_PHYSICAL" and all(
                len(link) == 2 for link in path):
            path = self._materialize_physical_path(path, spec.flow_id)
        if any(link not in self.edges and link not in self.physical_edges
               for link in path):
            raise ValueError(
                "FlowSim path_override contains a non-physical directed link "
                "for flow %s" % spec.flow_id)
        if any(left[1] != right[0] for left, right in zip(path, path[1:])):
            raise ValueError(
                "FlowSim path_override is not contiguous for flow %s"
                % spec.flow_id)
        return path

    @staticmethod
    def _waterfill(flow_ids, paths, capacities):
        """Allocate max-min rates in bytes/s for a set of active flows."""
        # The event ledger can contain thousands of EP peer flows, while a
        # small Clos has only a small number of distinct directed paths.  All
        # active flows with the same path receive the same max-min rate.  Do
        # the water-filling on path groups and expand the result once at the
        # end; scanning every flow once per water-fill round made large
        # high-concurrency replays quadratic in the number of peer flows.
        grouped = defaultdict(list)
        for flow_id in flow_ids:
            grouped[tuple(paths[flow_id])].append(flow_id)
        group_rates = {path: 0.0 for path in grouped}
        remaining = set(grouped)
        # Maintain path-group incidence explicitly.  The previous
        # implementation rebuilt ``[path for path in remaining if link in
        # path]`` for every residual link on every water-fill round.  With
        # EP64 this is thousands of distinct endpoint paths and made the
        # final few P2D flows spend most of their wall time in Python rate
        # allocation.  The incidence/count representation is mathematically
        # identical, but removes the repeated link-by-path scans.
        link_paths = defaultdict(list)
        link_flow_counts = defaultdict(int)
        for path, members in grouped.items():
            for link in set(path):
                link_paths[link].append(path)
                link_flow_counts[link] += len(members)
        # Keep links whose residual is exactly zero.  Dropping a saturated
        # link here would let a lower-priority flow allocate against another
        # unconstrained hop of the same path and then exceed the saturated
        # link capacity.  A zero share below is the intended strict-priority
        # wait state.
        residual = {
            link: max(float(capacity), 0.0)
            for link, capacity in capacities.items()
        }
        while remaining:
            shares = [
                (capacity / link_flow_counts[link], link)
                for link, capacity in residual.items()
                if link_flow_counts[link] > 0
            ]
            if not shares:
                break
            increment, _ = min(shares)
            # A zero residual capacity is a valid result under strict
            # priority: the lower class waits until a higher-class flow ends.
            # Assigning an artificial 1e-12 B/s rate here creates an enormous
            # completion time and, after float rounding, can create a zero-time
            # event loop.
            if increment <= 0.0:
                break
            for path in remaining:
                group_rates[path] += increment
            saturated_links = []
            for link, count in link_flow_counts.items():
                if count <= 0:
                    continue
                residual[link] -= increment * count
                if residual[link] <= 1.0e-9:
                    saturated_links.append(link)
            saturated = set()
            for link in saturated_links:
                saturated.update(
                    path for path in link_paths[link] if path in remaining)
            if not saturated:
                # Numerical roundoff or a disconnected residual map should
                # never turn into a busy loop.  Return the conservative rates
                # already assigned in this round.
                break
            remaining.difference_update(saturated)
            for path in saturated:
                for link in set(path):
                    link_flow_counts[link] -= len(grouped[path])
        return {
            flow_id: group_rates[path]
            for path, members in grouped.items()
            for flow_id in members
        }

    def _rates(self, active, paths):
        if not active:
            return {}
        capacities = {}
        for flow_id in active:
            for link in paths[flow_id]:
                capacities[link] = self._edge(link)["capacity_Bps"]
        if self.policy in ("KV_ISOLATED", "EP_ISOLATED"):
            isolated_name = ("KV_MOVEMENT" if self.policy == "KV_ISOLATED"
                              else "EP")
            isolated = [fid for fid in active
                        if active[fid]["spec"].traffic_class == isolated_name]
            shared = [fid for fid in active if fid not in isolated]
            # Counterfactual upper bound: the selected class gets a separate
            # virtual copy of every directed link, while the other classes
            # retain their original shared fabric.  No serving event, byte
            # count, or route changes; only cross-class capacity sharing is
            # removed.  This is intentionally not presented as a deployable
            # switch policy.
            rates = self._waterfill(isolated, paths, capacities) if isolated else {}
            rates.update(self._waterfill(shared, paths, capacities) if shared else {})
            self._debug_rates(active, paths, rates)
            return rates
        if self.policy == "FAIR":
            rates = self._waterfill(list(active), paths, capacities)
            self._debug_rates(active, paths, rates)
            return rates

        if self.policy == "CRITICAL_ONLY":
            high = [fid for fid in active
                    if (active[fid]["spec"].traffic_class == "EP" and
                        fid in self.critical_flow_ids)]
        else:
            high_name = "EP" if self.policy == "EP_FIRST" else "KV_MOVEMENT"
            high = [fid for fid in active
                    if active[fid]["spec"].traffic_class == high_name]
        # Use a set for membership. At high concurrency ``active`` can hold
        # tens of thousands of flows; list membership here made every strict
        # priority event quadratic in the number of active flows.
        high_set = set(high)
        low = [fid for fid in active if fid not in high_set]
        if not high:
            rates = self._waterfill(list(active), paths, capacities)
            self._debug_rates(active, paths, rates)
            return rates
        rates = self._waterfill(high, paths, capacities)
        residual = dict(capacities)
        # Accumulate high-class load once. Scanning every high-priority flow
        # for every link made large strict-priority replays unnecessarily
        # expensive when many endpoint paths were active.
        high_link_rates = defaultdict(float)
        for fid in high:
            rate = rates[fid]
            for link in paths[fid]:
                high_link_rates[link] += rate
        for link in residual:
            residual[link] = max(
                residual[link] - high_link_rates.get(link, 0.0), 0.0)
        rates.update(self._waterfill(low, paths, residual))
        self._debug_rates(active, paths, rates)
        return rates

    def _debug_rates(self, active, paths, rates):
        path = os.environ.get("FLOWSIM_RATE_DEBUG_PATH")
        limit = max(0, int(os.environ.get("FLOWSIM_RATE_DEBUG_LIMIT", "32")))
        if not path or self._rate_debug_count >= limit:
            return
        self._rate_debug_count += 1
        import json
        link_rates = defaultdict(float)
        link_capacity = {}
        for flow_id, data in active.items():
            for link in paths[flow_id]:
                link_rates[link] += rates.get(flow_id, 0.0)
                link_capacity[link] = self._edge(link)["capacity_Bps"]
        with open(path, "a", encoding="utf-8") as stream:
            stream.write(json.dumps({
                "policy": self.policy,
                "clock_ns": getattr(self, "clock_ns", None),
                "active": len(active),
                "classes": {
                    name: sum(1 for data in active.values()
                              if data["spec"].traffic_class == name)
                    for name in ("KV_MOVEMENT", "EP", "OTHER")},
                "rates": [
                    {"class": active[fid]["spec"].traffic_class,
                     "subtype": active[fid]["spec"].traffic_subtype,
                     "path": [self._link_name(link) for link in paths[fid]],
                     "rate_Bps": rates.get(fid, 0.0)}
                    for fid in list(active)[:8]],
                "link_utilization": {
                    self._link_name(link): {
                        "rate_Bps": link_rates[link],
                        "capacity_Bps": link_capacity[link],
                        "utilization": link_rates[link] / link_capacity[link],
                    }
                    for link in link_rates
                },
            }, sort_keys=True) + "\n")

    def simulate(self, specs):
        """Simulate one scheduler graph/collective and return flow finishes.

        The backend is intentionally stateless across scheduler graphs.  The
        serving frontend serializes graph rounds, while a group command puts
        all participants of one collective into this call.  Cross-request
        overlap is represented when multiple flows are in the same graph
        round; a later integration can retain active flows across rounds.
        """
        self.telemetry = []
        self.last_flows = []
        if not specs:
            return {}
        flow_data = {}
        paths = {}
        for spec in specs:
            start_ns = int(spec.start_ns)
            if int(spec.bytes) <= 0 or int(spec.src) == int(spec.dst):
                flow_data[spec.flow_id] = {
                    "spec": spec, "start_ns": start_ns, "remaining": 0.0}
                paths[spec.flow_id] = []
            else:
                flow_data[spec.flow_id] = {
                    "spec": spec, "start_ns": start_ns,
                    "remaining": float(int(spec.bytes))}
                paths[spec.flow_id] = self._resolve_flow_path(spec)

        finished = {
            fid: flow_data[fid]["start_ns"]
            for fid in flow_data
            if flow_data[fid]["remaining"] <= 0.0
        }
        arrivals = [
            fid for fid in sorted(flow_data, key=lambda fid: flow_data[fid]["start_ns"])
            if flow_data[fid]["remaining"] > 0.0
        ]
        next_arrival = 0
        active = {}
        now = min([flow_data[fid]["start_ns"] for fid in flow_data] or [0])
        event_count = 0
        # With integer completion events, each positive-size flow can be
        # admitted once and completed once.  This guard catches a regression
        # immediately instead of allowing a runaway process to consume RAM.
        event_limit = max(256, 4 * len(flow_data) + 16)
        while next_arrival < len(arrivals) or active:
            while next_arrival < len(arrivals):
                fid = arrivals[next_arrival]
                if flow_data[fid]["start_ns"] > now:
                    break
                active[fid] = flow_data[fid]
                next_arrival += 1
            if not active:
                now = flow_data[arrivals[next_arrival]]["start_ns"]
                continue
            rates = self._rates(active, paths)
            completion_times = {}
            for fid, data in active.items():
                rate = rates.get(fid, 0.0)
                if rate <= 0:
                    continue
                # Compute the duration before adding it to the absolute clock.
                # Keeping the clock and event duration integral prevents a
                # large absolute timestamp from rounding a tiny final event
                # back to ``now`` forever.
                duration_ns = int(math.ceil(
                    data["remaining"] * 1_000_000_000.0 / rate))
                completion_times[fid] = now + max(duration_ns, 1)
            next_time = min(completion_times.values(), default=None)
            if next_arrival < len(arrivals):
                candidate = flow_data[arrivals[next_arrival]]["start_ns"]
                if next_time is None or candidate < next_time:
                    next_time = candidate
            if next_time is None:
                raise RuntimeError(
                    "FlowSim could not make progress with active flows: "
                    "all active flows have zero residual capacity")
            next_time = int(next_time)
            if next_time <= now:
                # This is only possible for a same-timestamp arrival or a
                # malformed caller.  Admit arrivals first; otherwise fail
                # explicitly rather than spinning at one clock value.
                if next_arrival < len(arrivals) and (
                        flow_data[arrivals[next_arrival]]["start_ns"] <= now):
                    continue
                raise RuntimeError(
                    "FlowSim event clock made no progress at %d ns" % now)
            delta_ns = next_time - now
            link_rates = defaultdict(float)
            link_queue = defaultdict(float)
            for fid, data in active.items():
                rate = rates.get(fid, 0.0)
                data["remaining"] = max(data["remaining"] - rate * delta_ns / 1_000_000_000.0, 0.0)
                for link in paths[fid]:
                    link_rates[link] += rate
                    link_queue[link] += data["remaining"]
            self._append_link_telemetry(
                active, paths, rates, link_rates, link_queue, now, next_time)
            now = next_time
            completed = [fid for fid, candidate in completion_times.items()
                         if candidate <= next_time]
            for fid in completed:
                data = active.pop(fid)
                data["remaining"] = 0.0
                propagation = sum(self._edge(link)["latency_ns"]
                                  for link in paths[fid])
                finished[fid] = int(now + propagation)
                spec = data["spec"]
                self.last_flows.append({
                    "flow_id": spec.flow_id,
                    "src": spec.src,
                    "dst": spec.dst,
                    "bytes": spec.bytes,
                    "traffic_class": spec.traffic_class,
                    "traffic_subtype": spec.traffic_subtype,
                    "requested_start_ns": spec.start_ns,
                    "start_ns": data["start_ns"],
                    "end_ns": finished[fid],
                    "path": [self._link_name(link) for link in paths[fid]],
                    "mtu": None,
                    "request_ids": list(getattr(spec, "request_ids", ()) or ()),
                    "batch_id": getattr(spec, "batch_id", None),
                    "layer_id": getattr(spec, "layer_id", None),
                    "event_type": getattr(spec, "event_type", None),
                    "collective_id": getattr(spec, "collective_id", None),
                    "collective_type": getattr(spec, "collective_type", None),
                    "push_start_tokens": getattr(spec, "push_start_tokens", None),
                    "push_end_tokens": getattr(spec, "push_end_tokens", None),
                    "push_final": getattr(spec, "push_final", None),
                    "push_epoch": getattr(spec, "push_epoch", None),
                    "push_settled_tokens": getattr(spec, "push_settled_tokens", None),
                })
            event_count += 1
            if event_count > event_limit:
                raise RuntimeError(
                    "FlowSim event limit exceeded (%d events for %d flows)" %
                    (event_count, len(flow_data)))
        return finished


class PersistentFluidFlowNetwork(FluidFlowNetwork):
    """Persistent cross-graph fluid network for integrated serving runs.

    ``FluidFlowNetwork.simulate`` is intentionally a closed replay primitive:
    every call starts with an empty active-flow set.  That is sufficient for a
    ledger replay, but it cannot model a P2D flow opened by one scheduler graph
    while another request's EP graph is still in flight.  This subclass keeps
    pending and active flows between calls while preserving the same
    max-min/priority allocator and exact completion timestamps.

    The state is bounded by active/pending flows, not by a packet expansion.
    Telemetry remains residual fluid and is capped by ``max_telemetry_rows``.
    """

    def __init__(self, topology_path, policy="FAIR",
                 kv_backpressure="OFF", kv_buffer_bytes=0,
                 critical_flow_file=None, parallel_link_mode="AGGREGATE"):
        super().__init__(topology_path, policy, parallel_link_mode)
        self.clock_ns = 0
        self._sequence = 0
        self._pending = []
        self._blocked_kv = defaultdict(deque)
        self._active = {}
        self._finished = {}
        self._finished_records = {}
        self._seen = set()
        self.kv_backpressure = str(kv_backpressure).upper()
        self.kv_buffer_bytes = max(0, int(kv_buffer_bytes))
        self._kv_buffered = defaultdict(int)
        self._release_times = {}
        self._release_callback = None
        self.critical_flow_ids = self._read_critical_flow_file(
            critical_flow_file)

    @staticmethod
    def _read_critical_flow_file(path):
        if not path:
            return set()
        if not os.path.isfile(path):
            raise FileNotFoundError(
                "FlowSim critical-flow oracle does not exist: %s" % path)
        critical = set()
        with open(path, "r", encoding="utf-8") as stream:
            for line in stream:
                line = line.strip()
                if line and not line.startswith("#"):
                    critical.add(line)
        return critical

    @property
    def kv_backpressure_enabled(self):
        return (self.kv_backpressure == "FINITE_BUFFER" and
                self.kv_buffer_bytes > 0)

    def set_release_callback(self, callback):
        """Register an observational callback for actual KV network release."""
        self._release_callback = callback

    @staticmethod
    def _kv_scope(spec):
        request_ids = tuple(getattr(spec, "request_ids", ()) or ())
        if len(request_ids) == 1:
            return int(spec.src), str(request_ids[0])
        batch_id = getattr(spec, "batch_id", None)
        if batch_id is not None:
            return int(spec.src), "batch:%s" % batch_id
        return int(spec.src), "flow:%s" % spec.flow_id

    def _kv_capacity(self, data):
        # A single model-derived layer shard must be admissible even when a
        # sensitivity buffer smaller than that shard is requested; otherwise
        # the model would deadlock before the first transfer can start.
        return max(self.kv_buffer_bytes, int(data["spec"].bytes))

    def _notify_release(self, data):
        spec = data["spec"]
        timestamp = int(data["start_ns"])
        self._release_times[spec.flow_id] = timestamp
        if self._release_callback is not None:
            self._release_callback(spec, timestamp)

    def flow_release_time(self, flow_id):
        return self._release_times.get(flow_id)

    def _enqueue_pending(self, data):
        flow_id = data["spec"].flow_id
        self._sequence += 1
        heapq.heappush(self._pending,
                       (int(data["start_ns"]), self._sequence,
                        flow_id, data))
        self._notify_release(data)

    def _promote_blocked_kv(self):
        if not self.kv_backpressure_enabled:
            return
        for scope in list(self._blocked_kv):
            blocked = self._blocked_kv[scope]
            while blocked:
                data = blocked[0]
                spec = data["spec"]
                capacity = self._kv_capacity(data)
                if self._kv_buffered[scope] + int(spec.bytes) > capacity:
                    break
                blocked.popleft()
                self._kv_buffered[scope] += int(spec.bytes)
                data["start_ns"] = max(int(data["requested_ns"]),
                                        int(self.clock_ns))
                self._enqueue_pending(data)
            if not blocked:
                del self._blocked_kv[scope]

    def _record_flow(self, data, now_ns):
        spec = data["spec"]
        path = data["path"]
        propagation = sum(self._edge(link)["latency_ns"] for link in path)
        finish = int(now_ns + propagation)
        self._finished[spec.flow_id] = finish
        record = {
            "flow_id": spec.flow_id,
            "src": spec.src,
            "dst": spec.dst,
            "bytes": spec.bytes,
            "traffic_class": spec.traffic_class,
            "traffic_subtype": spec.traffic_subtype,
            # ``spec.start_ns`` is the requested release time.  A persistent
            # flow can be submitted while the network clock is later than
            # that request time.  Expose the actual service start separately
            # so post-processing cannot invent KV/EP overlap.
            "requested_start_ns": spec.start_ns,
            "start_ns": data["start_ns"],
            "end_ns": finish,
            "path": [self._link_name(link) for link in path],
            "mtu": None,
            "request_ids": list(getattr(spec, "request_ids", ()) or ()),
            "batch_id": getattr(spec, "batch_id", None),
            "layer_id": getattr(spec, "layer_id", None),
            "event_type": getattr(spec, "event_type", None),
            "collective_id": getattr(spec, "collective_id", None),
            "collective_type": getattr(spec, "collective_type", None),
            "push_start_tokens": getattr(spec, "push_start_tokens", None),
            "push_end_tokens": getattr(spec, "push_end_tokens", None),
            "push_final": getattr(spec, "push_final", None),
            "push_epoch": getattr(spec, "push_epoch", None),
            "push_settled_tokens": getattr(spec, "push_settled_tokens", None),
        }
        self._finished_records[spec.flow_id] = record
        self.last_flows.append(record)

    def _install(self, specs):
        target_ids = []
        for spec in specs:
            flow_id = spec.flow_id
            if flow_id in self._seen:
                target_ids.append(flow_id)
                continue
            self._seen.add(flow_id)
            target_ids.append(flow_id)
            start_ns = max(int(spec.start_ns), int(self.clock_ns))
            # A self-communication has no scale-out path.  Treat it as an
            # immediately completed local operation, just as the closed
            # replay path does.  Leaving its positive byte count in
            # ``_active`` creates a zero-rate, pathless fluid flow; once it
            # is the last active flow, ``next_event_time`` returns None and
            # the integrated frontend can never retire the graph.
            local_or_empty = (int(spec.bytes) <= 0 or
                               int(spec.src) == int(spec.dst))
            path = [] if local_or_empty else self._resolve_flow_path(spec)
            data = {
                "spec": spec,
                "path": path,
                "remaining": 0.0 if local_or_empty else float(max(0, int(spec.bytes))),
                "start_ns": start_ns,
            }
            if data["remaining"] <= 0.0:
                self._finished[flow_id] = start_ns
                continue
            data["requested_ns"] = int(spec.start_ns)
            if (self.kv_backpressure_enabled and
                    spec.traffic_class == "KV_MOVEMENT"):
                scope = self._kv_scope(spec)
                data["kv_scope"] = scope
                capacity = self._kv_capacity(data)
                if (self._kv_buffered[scope] + int(spec.bytes) > capacity):
                    self._blocked_kv[scope].append(data)
                    continue
                self._kv_buffered[scope] += int(spec.bytes)
            self._enqueue_pending(data)
        return target_ids

    def submit(self, specs):
        """Install flows without waiting for them to finish.

        The interactive serving frontend can have a Prefill graph and a
        Decode graph outstanding at the same time.  ``simulate`` remains the
        convenient blocking API used by replay tools; this method is the
        event-driven counterpart used by the integrated worker.
        """
        if not specs:
            return []
        new_ids = [spec.flow_id for spec in specs
                   if spec.flow_id not in self._seen]
        if new_ids:
            self.last_flows = []
        return self._install(specs)

    def _advance_one(self, limit_ns=None):
        """Advance the global fluid network to its next event or a limit.

        The integrated serving worker has accelerator/local-compute events
        that can occur before a network flow completes.  A closed flow
        simulator may jump directly to the completion event, but doing that
        here would skip a Decode collective released in the middle of a large
        P2D transfer.  ``limit_ns`` lets the caller advance fluid residuals
        only up to the next frontend event and then submit the newly released
        communication.
        """
        while self._pending and self._pending[0][0] <= self.clock_ns:
            _, _, flow_id, data = heapq.heappop(self._pending)
            if flow_id in self._finished:
                continue
            self._active[flow_id] = data
        if not self._active:
            if not self._pending:
                return []
            self.clock_ns = max(self.clock_ns, int(self._pending[0][0]))
            while self._pending and self._pending[0][0] <= self.clock_ns:
                _, _, flow_id, data = heapq.heappop(self._pending)
                if flow_id not in self._finished:
                    self._active[flow_id] = data
            if not self._active:
                return []

        paths = {flow_id: data["path"]
                 for flow_id, data in self._active.items()}
        rates = self._rates(self._active, paths)
        completion_times = {}
        for flow_id, data in self._active.items():
            rate = rates.get(flow_id, 0.0)
            if rate > 0.0:
                duration_ns = int(math.ceil(
                    data["remaining"] * 1_000_000_000.0 / rate))
                completion_times[flow_id] = self.clock_ns + max(duration_ns, 1)
        next_time = min(completion_times.values(), default=None)
        if self._pending:
            next_arrival = int(self._pending[0][0])
            if next_time is None or next_arrival < next_time:
                next_time = next_arrival
        if limit_ns is not None:
            limit_ns = int(limit_ns)
            if limit_ns > self.clock_ns and (
                    next_time is None or limit_ns < next_time):
                next_time = limit_ns
        if next_time is None:
            raise RuntimeError(
                "Persistent FlowSim cannot make progress: all active flows have zero rate")
        next_time = int(next_time)
        if next_time <= self.clock_ns:
            raise RuntimeError(
                "Persistent FlowSim event clock made no progress at %d ns" % self.clock_ns)

        delta_ns = next_time - self.clock_ns
        link_rates = defaultdict(float)
        link_queue = defaultdict(float)
        for flow_id, data in self._active.items():
            rate = rates.get(flow_id, 0.0)
            data["remaining"] = max(
                data["remaining"] - rate * delta_ns / 1_000_000_000.0, 0.0)
            for link in data["path"]:
                link_rates[link] += rate
                link_queue[link] += data["remaining"]
        self._append_link_telemetry(
            self._active, paths, rates, link_rates, link_queue,
            self.clock_ns, next_time)
        self.clock_ns = next_time
        completed = [flow_id for flow_id, candidate in completion_times.items()
                     if candidate <= next_time]
        for flow_id in completed:
            data = self._active.pop(flow_id)
            data["remaining"] = 0.0
            self._record_flow(data, self.clock_ns)
            if data["spec"].traffic_class == "KV_MOVEMENT" and \
                    self.kv_backpressure_enabled:
                scope = data.get("kv_scope")
                if scope is not None:
                    self._kv_buffered[scope] = max(
                        0, self._kv_buffered[scope] -
                        int(data["spec"].bytes))
            self._promote_blocked_kv()
        return completed

    def advance(self):
        """Advance once and return the flow ids completed at the new clock."""
        return self._advance_one()

    def advance_until(self, target_ns):
        """Advance no later than ``target_ns`` and return completed flows."""
        return self._advance_one(limit_ns=int(target_ns))

    def flow_finished(self, flow_id):
        return flow_id in self._finished

    def flow_finish(self, flow_id):
        return self._finished.get(flow_id)

    def flow_record(self, flow_id):
        return self._finished_records.get(flow_id)

    def release_flow_record(self, flow_id):
        """Drop the verbose completed-flow record after telemetry is emitted.

        Completion timestamps remain in the compact ``_finished`` map so a
        late waiter can still observe the barrier, while the path/spec dict is
        not retained for the rest of a long serving trace.
        """
        self._finished_records.pop(flow_id, None)

    def retire_flow(self, flow_id):
        """Release compact state for a flow whose graph waiters are done.

        The integrated executor keeps the network alive across scheduler
        graphs.  ``_finished`` and ``_seen`` are needed while a completed
        flow can still be observed by a late graph waiter, but retaining every
        completed Decode-EP flow for the whole serving run turns an EP64 trace
        into an avoidable memory leak.  The executor calls this only after it
        has released all current waiters and emitted telemetry.
        """
        self._finished_records.pop(flow_id, None)
        self._finished.pop(flow_id, None)
        self._seen.discard(flow_id)
        self._release_times.pop(flow_id, None)

    def next_event_time(self):
        """Return the next fluid arrival/completion without advancing time."""
        if not self._active:
            return int(self._pending[0][0]) if self._pending else None
        paths = {flow_id: data["path"]
                 for flow_id, data in self._active.items()}
        rates = self._rates(self._active, paths)
        next_time = None
        for flow_id, data in self._active.items():
            rate = rates.get(flow_id, 0.0)
            if rate <= 0.0:
                continue
            duration_ns = int(math.ceil(
                data["remaining"] * 1_000_000_000.0 / rate))
            candidate = self.clock_ns + max(duration_ns, 1)
            next_time = candidate if next_time is None else min(next_time, candidate)
        if next_time is None and self._active:
            blocked = []
            for flow_id, data in list(self._active.items())[:8]:
                spec = data["spec"]
                blocked.append({
                    "flow_id": flow_id,
                    "class": spec.traffic_class,
                    "subtype": spec.traffic_subtype,
                    "src": spec.src,
                    "dst": spec.dst,
                    "bytes_remaining": data["remaining"],
                    "path": [self._link_name(link) for link in data["path"]],
                    "rate_Bps": rates.get(flow_id, 0.0),
                })
            raise RuntimeError(
                "Persistent FlowSim has active flows but no positive-rate "
                "event at %d ns: %s" % (self.clock_ns, blocked))
        if self._pending:
            candidate = int(self._pending[0][0])
            next_time = candidate if next_time is None else min(next_time, candidate)
        return next_time

    def _run_until(self, target_ids):
        targets = {flow_id for flow_id in target_ids
                   if flow_id not in self._finished}
        event_limit = max(256, 4 * (len(target_ids) + len(self._active) + len(self._pending)) + 16)
        event_count = 0
        while targets:
            completed = self._advance_one()
            targets.difference_update(completed)
            event_count += 1
            if event_count > event_limit:
                raise RuntimeError(
                    "Persistent FlowSim event limit exceeded (%d events, %d targets)" %
                    (event_count, len(target_ids)))

    def simulate(self, specs):
        """Submit graph flows and wait only for those graph flows to finish."""
        if not specs:
            self.last_flows = []
            return {}
        # A GraphExecutor fixed-point pass submits the same graph ids again.
        # Preserve the first pass' completed-flow records so the executor can
        # emit telemetry after its dependency resolution, but clear records
        # when a genuinely new graph is submitted.
        new_ids = [spec.flow_id for spec in specs if spec.flow_id not in self._seen]
        if new_ids:
            self.last_flows = []
        target_ids = self._install(specs)
        self._run_until(target_ids)
        return {flow_id: self._finished[flow_id] for flow_id in target_ids}
