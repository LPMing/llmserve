"""Interactive FlowSim worker for LLMServingSim's scheduler frontend.

The worker speaks the same line protocol as the HTSim interactive frontend:
one completion report, ``Waiting``, then one command.  It consumes Chakra ET
graphs produced by the native trace generator, so compute durations, P2D
bytes, and MoE routing remain native/model-derived.  Network completion is
replaced by a directed fluid max-min flow calculation.
"""

import argparse
import csv
from collections import deque
import heapq
import json
import math
import os
import re
import sys

try:
    from .flowsim_backend import FlowSpec, FluidFlowNetwork, PersistentFluidFlowNetwork
except ImportError:
    # The serving frontend launches this file as a standalone worker process.
    from flowsim_backend import FlowSpec, FluidFlowNetwork, PersistentFluidFlowNetwork


_RE_RANK = re.compile(r"llm\.(\d+)\.et$")


def _chakra_imports():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    chakra_root = os.path.join(repo_root, "astra-sim", "extern", "graph_frontend", "chakra")
    if chakra_root not in sys.path:
        sys.path.insert(0, chakra_root)
    from schema.protobuf.et_def_pb2 import (  # pylint: disable=import-outside-toplevel
        COMM_COLL_NODE, COMM_RECV_NODE, COMM_SEND_NODE, Node, GlobalMetadata,
    )
    from src.third_party.utils.protolib import (  # pylint: disable=import-outside-toplevel
        decodeMessage, openFileRd,
    )
    return Node, GlobalMetadata, COMM_SEND_NODE, COMM_RECV_NODE, COMM_COLL_NODE, decodeMessage, openFileRd


def _attr(node, name, default=None):
    for attr in node.attr:
        if attr.name != name:
            continue
        field = attr.WhichOneof("value")
        if field is None:
            return default
        return getattr(attr, field)
    return default


def _request_ids(node):
    """Read converter-attached request provenance without inventing splits."""
    value = _attr(node, "request_ids", "")
    if value is None:
        return ()
    return tuple(int(item) for item in str(value).split(";") if item != "")


def _flow_metadata(node, fallback_collective_id=None):
    """Return stable serving metadata carried by a Chakra communication node."""
    return {
        "request_ids": _request_ids(node),
        "batch_id": _attr(node, "batch_id", None),
        "collective_batch_id": _attr(
            node, "collective_batch_id", _attr(node, "batch_id", None)),
        "layer_id": _attr(node, "layer_id", None),
        "event_type": _attr(node, "event_type", None),
        "collective_id": _attr(node, "collective_id", fallback_collective_id),
        "push_start_tokens": _attr(node, "push_start_tokens", None),
        "push_end_tokens": _attr(node, "push_end_tokens", None),
        "push_final": _attr(node, "push_final", None),
        "push_epoch": _attr(node, "push_epoch", None),
        "push_settled_tokens": _attr(node, "push_settled_tokens", None),
    }


def _read_graph(path):
    Node, GlobalMetadata, _, _, _, decode_message, open_file = _chakra_imports()
    if not os.path.isfile(path):
        raise FileNotFoundError("FlowSim ET graph does not exist: %s" % path)
    stream = open_file(path)
    metadata = GlobalMetadata()
    if not decode_message(stream, metadata):
        stream.close()
        raise ValueError("invalid Chakra ET metadata: %s" % path)
    nodes = []
    while True:
        node = Node()
        if not decode_message(stream, node):
            break
        nodes.append(node)
    stream.close()
    match = _RE_RANK.search(path)
    if not match:
        raise ValueError("cannot infer rank from ET path: %s" % path)
    return int(match.group(1)), nodes


def _graph_paths(command, ranks):
    """Resolve a workload prefix or a direct ET path for rank ids."""
    result = []
    if command.endswith(".et"):
        rank, _ = _read_graph(command)
        return [(rank, command)]
    for rank in ranks:
        result.append((int(rank), os.path.join(command + ".%d.et" % int(rank))))
    return result


_COLLECTIVE_TYPE_NAMES = {
    0: "ALLREDUCE",
    1: "REDUCE",
    2: "ALLGATHER",
    3: "GATHER",
    4: "SCATTER",
    5: "BROADCAST",
    6: "ALLTOALL",
    7: "REDUCESCATTER",
    8: "REDUCESCATTER_BLOCK",
    9: "BARRIER",
}


def _collective_type_name(node):
    value = _attr(node, "comm_type", None)
    try:
        return _COLLECTIVE_TYPE_NAMES.get(int(value), "UNKNOWN")
    except (TypeError, ValueError):
        return "UNKNOWN"


def _collective_peer_bytes(node, comm_size, participant_count):
    """Return one direct peer payload for a FlowSim collective expansion.

    Chakra's ``comm_size`` is the collective's per-rank input size, but its
    meaning differs by collective.  The previous adapter used
    ``comm_size/(N-1)`` for every type, which undercounted AllGather by N-1
    and did not represent the per-destination chunk of ReduceScatter or
    AllToAll.  FlowSim is still an analytical direct-peer approximation; this
    helper only makes the bytes match the documented collective contract.
    """
    size = max(0, int(comm_size))
    participants = max(1, int(participant_count))
    collective_type = _collective_type_name(node)
    if collective_type == "ALLGATHER":
        # Each rank contributes its local input chunk to every other rank.
        return size
    if collective_type in ("REDUCESCATTER", "REDUCESCATTER_BLOCK",
                            "ALLTOALL", "ALLREDUCE"):
        # Direct peer approximation: one destination-sized chunk per remote
        # peer.  For ReduceScatter/AllReduce the input buffer is partitioned;
        # for AllToAll this is the per-destination slice of the input buffer.
        return max(1, int(math.ceil(float(size) / participants)))
    # Keep a conservative fallback for collective types that are not part of
    # the MoE path rather than silently creating a zero-byte operation.
    return max(1, int(math.ceil(float(size) / max(participants - 1, 1))))


def _phase_class(name, node=None):
    # Converter metadata is authoritative.  The name fallback keeps old ET
    # graphs readable when they predate serving provenance attributes.
    event_type = _attr(node, "event_type", None) if node is not None else None
    if event_type == 1:
        return "KV_MOVEMENT", "P2D"
    if event_type == 2:
        return "EP", "EP_DISPATCH"
    if event_type == 3:
        return "EP", "EP_COMBINE"
    if event_type == 4:
        return "KV_MOVEMENT", "NIXL_PUSH_WRITE"
    if event_type == 5:
        return "OTHER", "NIXL_PUSH_COMMIT"
    if event_type == 6:
        return "OTHER", "NIXL_PUSH_SETTLEMENT"
    lower = name.lower()
    if "kv_proj" in lower or "kv" in lower:
        return "KV_MOVEMENT", "P2D"
    if "expert_start" in lower or "expert_end" in lower or "alltoall" in lower:
        subtype = "EP_DISPATCH" if "start" in lower else "EP_COMBINE"
        return "EP", subtype
    return "OTHER", "OTHER"


class GraphExecutor:
    def __init__(self, network, telemetry_path=None, decode_ranks=None):
        self.network = network
        self.telemetry_path = telemetry_path
        self.decode_ranks = (None if decode_ranks is None else
                             {int(rank) for rank in decode_ranks})
        self.p2d_finish = {}
        if telemetry_path:
            parent = os.path.dirname(telemetry_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(telemetry_path, "w", encoding="utf-8") as stream:
                stream.write("# FlowSim fluid telemetry; queue_bytes is residual fluid, not packet queue\n")

    def _write_telemetry(self, graph_id, flows):
        if not self.telemetry_path:
            return
        with open(self.telemetry_path, "a", encoding="utf-8") as stream:
            for record in flows:
                row = dict(record)
                row["graph_id"] = graph_id
                stream.write(json.dumps(row, sort_keys=True) + "\n")

    def simulate(self, now_ns, graph_items, graph_id):
        """Execute a set of rank graphs and return their common completion."""
        # Importing enum constants once here avoids importing Chakra at module
        # import time, which keeps the serving CLI's analytical path unchanged.
        Node, GlobalMetadata, send_type, recv_type, coll_type, _, _ = _chakra_imports()
        del Node, GlobalMetadata
        if not graph_items:
            return int(now_ns)
        previous_comm = {}
        final_flows = []
        final_node_finish = {}
        for _iteration in range(4):
            node_finish = {}
            operations = []
            coll_groups = {}
            for rank, nodes in graph_items:
                # Chakra converter allocates monotonically increasing node ids,
                # and dependencies always refer to earlier ids. Sorting makes
                # the adapter robust to protobuf windowing/order changes.
                for node in sorted(nodes, key=lambda item: int(item.id)):
                    ready = int(now_ns)
                    if node.data_deps:
                        ready = max(node_finish.get((rank, int(parent)), int(now_ns))
                                    for parent in node.data_deps)
                    if node.type not in (send_type, recv_type, coll_type):
                        node_finish[(rank, int(node.id))] = ready + int(node.duration_micros) * 1000
                        continue
                    traffic_class, subtype = _phase_class(node.name, node)
                    operation = {
                        "rank": rank,
                        "node_id": int(node.id),
                        "node": node,
                        "ready": ready,
                        "class": traffic_class,
                        "subtype": subtype,
                    }
                    operations.append(operation)
                    if node.type == coll_type:
                        collective_id = _attr(node, "collective_id", None)
                        key = ("coll", collective_id if collective_id is not None else node.name)
                        coll_groups.setdefault(key, []).append(operation)
                    else:
                        comm_key = (
                            int(_attr(node, "comm_src", rank)),
                            int(_attr(node, "comm_dst", rank)),
                            int(_attr(node, "comm_tag", int(node.id))),
                            int(_attr(node, "comm_size", 0)),
                        )
                        operation["comm_key"] = comm_key
                    # The previous iteration supplies a network completion;
                    # without one, the operation is initially zero-duration and
                    # gets a real finish after FlowSim runs below.
                    key = operation.get("comm_key") or ("coll", _attr(node, "collective_id", node.name))
                    node_finish[(rank, int(node.id))] = int(previous_comm.get(key, ready))

            specs = []
            spec_to_operation = {}
            sends = {}
            receives = {}
            for operation in operations:
                node = operation["node"]
                if node.type == send_type:
                    key = operation["comm_key"]
                    sends[key] = operation
                elif node.type == recv_type:
                    receives[operation["comm_key"]] = operation
            for key, operation in sends.items():
                src, dst, tag, size = key
                # P2D can be emitted in a sender graph and a receiver graph in
                # separate frontend commands. The sender is the authoritative
                # transfer; a later receive reuses its completion timestamp.
                if operation["subtype"] == "P2D" and key in self.p2d_finish:
                    previous_comm[key] = self.p2d_finish[key]
                    continue
                flow_id = "%s:%s:%s:%s" % (graph_id, src, dst, tag)
                spec = FlowSpec(flow_id, src, dst, size, operation["ready"],
                                operation["class"], operation["subtype"])
                specs.append(spec)
                spec_to_operation[flow_id] = (key, operation)
            for key, operation in receives.items():
                if key in sends:
                    continue
                src, dst, tag, size = key
                if operation["subtype"] == "P2D" and key in self.p2d_finish:
                    previous_comm[key] = self.p2d_finish[key]
                    continue
                flow_id = "%s:recv:%s:%s:%s" % (graph_id, src, dst, tag)
                spec = FlowSpec(flow_id, src, dst, size, operation["ready"],
                                operation["class"], operation["subtype"])
                specs.append(spec)
                spec_to_operation[flow_id] = (key, operation)
            for collective_key, group in coll_groups.items():
                participants = sorted({int(item["rank"]) for item in group})
                for operation in group:
                    ready = operation["ready"]
                    if len(participants) < 2:
                        previous_comm[collective_key] = ready
                        continue
                    size = int(_attr(operation["node"], "comm_size", 0))
                    per_peer = _collective_peer_bytes(
                        operation["node"], size, len(participants))
                    for dst in participants:
                        if dst == operation["rank"]:
                            continue
                        flow_id = "%s:coll:%s:%s:%s" % (graph_id, collective_key, operation["rank"], dst)
                        spec = FlowSpec(
                            flow_id, int(operation["rank"]), dst, per_peer,
                            ready, operation["class"], operation["subtype"],
                            collective_type=_collective_type_name(
                                operation["node"]))
                        specs.append(spec)
                        spec_to_operation[flow_id] = (collective_key, operation)

            finishes = self.network.simulate(specs)
            comm_finish = {}
            coll_finish = {}
            for flow_id, finish in finishes.items():
                key, operation = spec_to_operation[flow_id]
                if isinstance(key, tuple) and key and key[0] == "coll":
                    coll_finish[key] = max(coll_finish.get(key, 0), finish)
                else:
                    comm_finish[key] = max(comm_finish.get(key, 0), finish)
            previous_comm.update(comm_finish)
            previous_comm.update(coll_finish)
            for operation in operations:
                node = operation["node"]
                key = operation.get("comm_key") or ("coll", _attr(node, "collective_id", node.name))
                node_finish[(operation["rank"], operation["node_id"])] = int(
                    previous_comm.get(key, operation["ready"]))
            final_node_finish = node_finish
            final_flows = list(self.network.last_flows)
            if not comm_finish and not coll_finish:
                break
        for operation in operations:
            if operation["subtype"] == "P2D":
                key = operation.get("comm_key")
                if key in previous_comm:
                    self.p2d_finish[key] = previous_comm[key]
        self._write_telemetry(graph_id, final_flows)
        return max(final_node_finish.values() or [int(now_ns)])


class AsyncGraphExecutor:
    """DAG-aware nonblocking executor for concurrent serving graphs.

    The original adapter waited inside ``simulate`` for every flow in one ET
    graph.  That is correct for a closed replay, but it serializes a new
    Prefill graph behind an already-running Decode graph.  This executor keeps
    the Chakra node dependencies, submits ready network operations to the
    persistent FlowSim fabric, and lets the worker advance compute and network
    events together.  Consequently P2D from one request can overlap Decode EP
    from another request without changing scheduler admission semantics.
    """

    def __init__(self, network, telemetry_path=None, decode_ranks=None,
                 remote_kv_plan=None, remote_kv_mode='LEGACY'):
        self.network = network
        self.telemetry_path = telemetry_path
        # The completed-flow JSONL is useful for a small validation window,
        # but it is not part of serving/network semantics.  A long
        # integrated trace can otherwise spend most of its wall time
        # serialising KV/EP records.  Keep it enabled by default for backward
        # compatibility; large serving runs can disable only this output with
        # FLOWSIM_FLOW_TELEMETRY=0 while retaining collective/KV/link
        # telemetry and all completion callbacks.
        self.write_flow_telemetry = os.environ.get(
            "FLOWSIM_FLOW_TELEMETRY", "1").lower() not in (
                "0", "false", "no", "off")
        self.decode_ranks = (None if decode_ranks is None else
                             {int(rank) for rank in decode_ranks})
        self.remote_kv_plan = remote_kv_plan or {}
        self.remote_kv_mode = str(remote_kv_mode or 'LEGACY').upper()
        self.remote_kv_submitted = set()
        self.remote_kv_pending_specs = []
        self.replica_warmup_flow_ids = set()
        self.replica_warmup_complete = True
        self.jobs = {}
        self.local_events = []
        self.sequence = 0
        self.flow_waiters = {}
        self.flow_graph = {}
        self.flow_graph_path = {}
        # Progressive Push writes are real network flows but nonblocking DAG
        # nodes. Final commit nodes wait on every producer-rank write for the
        # request before releasing Decode admission.
        self.push_flow_info = {}
        self.push_commit_waiters = {}
        self.push_states = {}
        self.push_inflight_by_scope = {}
        self.push_pending_by_scope = {}
        # One barrier per group-wide collective replaces the old
        # flow-to-all-members waiter matrix.  The old representation attached
        # 64 node waiters to every one of 64-way all-to-all flows, and did so
        # for every MoE layer in a Decode graph.  EP64 then retained millions
        # of Python tuple/set entries before the first graph could finish.
        self.collective_flow_barriers = {}
        # A2A_P2P represents an EP round as many P2P nodes rather than one
        # Chakra collective node. Keep a lightweight round barrier for CCT
        # telemetry without retaining every peer flow in the main output.
        self.ep_p2p_flow_groups = {}
        self.flow_submitted = set()
        self.telemetry_written = set()
        self.kv_event_stream = None
        self.collective_event_stream = None
        self.ep_flow_event_stream = None
        self.push_event_stream = None
        self.push_request_stream = None
        self.max_ep_flow_telemetry_rows = max(
            0, int(os.environ.get("FLOWSIM_MAX_EP_FLOW_TELEMETRY_ROWS", "0")))
        self.ep_flow_telemetry_rows = 0
        self.ep_flow_telemetry_link_ids = {
            item.strip() for item in os.environ.get(
                "FLOWSIM_EP_FLOW_TELEMETRY_LINK_IDS", "").split(",")
            if item.strip()
        }
        # Residual-link telemetry and completed-flow telemetry have separate
        # controls.  The former is bounded by the network backend; the latter
        # can otherwise turn a long Decode trace into hundreds of thousands of
        # JSON writes.  Zero keeps the historical unlimited behavior.
        self.max_flow_telemetry_rows = max(
            0, int(os.environ.get("FLOWSIM_MAX_FLOW_TELEMETRY_ROWS", "0")))
        self.flow_telemetry_rows = 0
        # Integrated serving graphs contain a large amount of TP/OTHER
        # traffic. Persisting every completed control-plane flow makes even
        # a two-request gate produce hundreds of megabytes of JSON, while the
        # KV-vs-Decode-EP study only needs the two data-plane classes. This is
        # telemetry-only: all flows still enter the same fluid network and
        # completion callbacks are unchanged. Set
        # FLOWSIM_TELEMETRY_CLASSES=KV_MOVEMENT,EP,OTHER for a verbose run.
        configured_classes = os.environ.get(
            "FLOWSIM_TELEMETRY_CLASSES", "KV_MOVEMENT,EP")
        self.telemetry_classes = {
            value.strip() for value in configured_classes.split(",")
            if value.strip()
        }
        configured_network_classes = os.environ.get(
            "FLOWSIM_NETWORK_CLASSES", "KV_MOVEMENT,EP")
        self.network_classes = {
            value.strip() for value in configured_network_classes.split(",")
            if value.strip()
        }
        # A P2D transfer is a per-request communication instance.  Its
        # Chakra tag/size tuple is not globally unique: two requests can
        # legitimately produce the same (src, dst, tag, bytes).  Keeping a
        # single flow keyed only by that tuple silently re-used the first
        # request's completed transfer for all later requests.  Pair actual
        # sender and receiver nodes FIFO, while retaining each transfer as a
        # distinct FlowSim flow.
        self.p2d_waiters = {}
        self.p2d_unpaired_flows = {}
        self.p2d_unpaired_flow_ids = set()
        self.debug_path = os.environ.get("FLOWSIM_EXEC_DEBUG_PATH")
        self.debug_count = 0
        if telemetry_path:
            parent = os.path.dirname(telemetry_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(telemetry_path, "w", encoding="utf-8") as stream:
                stream.write(
                    "# FlowSim fluid telemetry; queue_bytes is residual fluid, "
                    "not packet queue; policy=%s\n" % self.network.policy)
            kv_path = os.path.join(parent or ".", "kv_event_telemetry.jsonl")
            self.kv_event_stream = open(kv_path, "w", encoding="utf-8")
            self.kv_event_stream.write(
                "# KV event telemetry; aggregate flows retain request_ids and "
                "are not split into fabricated per-request bytes\n")
            collective_path = os.path.join(parent or ".",
                                           "collective_telemetry.jsonl")
            self.collective_event_stream = open(collective_path, "w",
                                                encoding="utf-8")
            self.collective_event_stream.write(
                "# FlowSim collective-level telemetry; CCT is the last peer "
                "completion minus collective start\n")
            if os.environ.get("FLOWSIM_EP_FLOW_TELEMETRY", "0") == "1":
                ep_flow_path = os.path.join(parent or ".",
                                            "ep_flow_telemetry.jsonl")
                self.ep_flow_event_stream = open(ep_flow_path, "w",
                                                 encoding="utf-8")
                self.ep_flow_event_stream.write(
                    "# FlowSim EP per-flow collective telemetry; fluid model\n")
            push_path = os.path.join(parent or ".",
                                     "PROGRESSIVE_PUSH_EVENTS.csv")
            self.push_event_stream = open(push_path, "w", encoding="utf-8")
            self.push_event_stream.write(
                "event,timestamp_ns,request_id,rank,flow_id,epoch,start_tokens,end_tokens,"
                "settled_tokens,bytes,src,dst,final,mode\n")
            request_path = os.path.join(parent or ".",
                                        "PROGRESSIVE_PUSH_REQUESTS.csv")
            self.push_request_stream = open(request_path, "w", encoding="utf-8")
            self.push_request_stream.write(
                "request_id,first_settlement,last_settlement,last_write,commit,"
                "settled_tokens,posted_tokens,total_bytes,write_count,commit_rank_count\n")
        self._submit_replica_warmup()

    def _submit_replica_warmup(self):
        """Submit model-derived replica-copy flows before request fetches.

        Warm-up traffic is real FlowSim traffic and therefore consumes the
        same fabric. Remote fetches are held until every planned copy ends,
        so a balanced-replica run cannot silently assume zero-cost replicas.
        """
        warmup = self.remote_kv_plan.get("__warmup__", ())
        specs = []
        for index, item in enumerate(warmup):
            src = int(item["src"])
            dst = int(item["dst"])
            size = int(item["bytes"])
            if size <= 0 or src == dst:
                continue
            flow_id = str(item.get(
                "flow_id", "remote_kv_warmup:%d:%d:%d:%d" %
                (index, src, dst, size)))
            specs.append(FlowSpec(
                flow_id, src, dst, size, 0, "KV_MOVEMENT",
                "REMOTE_KV_REPLICATION", request_ids=(),
                layer_id=item.get("layer_id"), event_type=1))
        if not specs:
            return
        self.replica_warmup_complete = False
        self.replica_warmup_flow_ids = {spec.flow_id for spec in specs}
        for spec in specs:
            self.flow_submitted.add(spec.flow_id)
            self._write_kv_event(
                "KV_GENERATED", spec=spec, timestamp_ns=0)
        self.network.submit(specs)

    def _release_pending_remote_kv(self):
        pending = list(self.remote_kv_pending_specs)
        self.remote_kv_pending_specs.clear()
        for spec in pending:
            if spec.flow_id in self.flow_submitted:
                continue
            self.flow_submitted.add(spec.flow_id)
            self._write_kv_event(
                "KV_GENERATED", spec=spec, timestamp_ns=int(spec.start_ns))
            self.network.submit([spec])

    @staticmethod
    def _spec_metadata(spec):
        return {
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

    def _write_kv_event(self, event, spec=None, record=None, timestamp_ns=None):
        if self.kv_event_stream is None:
            return
        if record is not None:
            # PersistentFluidFlowNetwork exposes a flattened completion
            # record, not its internal ``spec`` object.  Keep completion
            # telemetry usable after the backend has retired that object.
            spec = record.get("spec")
            if spec is None:
                if record.get("traffic_class") != "KV_MOVEMENT":
                    return
                row = {
                    "event": event,
                    "timestamp_ns": (int(timestamp_ns)
                                     if timestamp_ns is not None else None),
                    "flow_id": record.get("flow_id"),
                    "src": record.get("src"),
                    "dst": record.get("dst"),
                    "bytes": record.get("bytes"),
                    "traffic_subtype": record.get("traffic_subtype"),
                    "request_ids": list(record.get("request_ids", ()) or ()),
                    "batch_id": record.get("batch_id"),
                    "layer_id": record.get("layer_id"),
                    "event_type": record.get("event_type"),
                    "collective_id": record.get("collective_id"),
                    "requested_start_ns": record.get("requested_start_ns"),
                    "start_ns": record.get("start_ns"),
                    "end_ns": record.get("end_ns"),
                    "path": record.get("path", []),
                }
                self.kv_event_stream.write(
                    json.dumps(row, sort_keys=True) + "\n")
                return
        if spec is None or getattr(spec, "traffic_class", None) != "KV_MOVEMENT":
            return
        row = {
            "event": event,
            "timestamp_ns": (int(timestamp_ns)
                             if timestamp_ns is not None else None),
            "flow_id": getattr(spec, "flow_id", None),
            "src": getattr(spec, "src", None),
            "dst": getattr(spec, "dst", None),
            "bytes": getattr(spec, "bytes", None),
            "traffic_subtype": getattr(spec, "traffic_subtype", None),
            **self._spec_metadata(spec),
        }
        if record is not None:
            row.update({
                "requested_start_ns": record.get("requested_start_ns"),
                "start_ns": record.get("start_ns"),
                "end_ns": record.get("end_ns"),
                "path": record.get("path", []),
            })
        self.kv_event_stream.write(json.dumps(row, sort_keys=True) + "\n")

    def _write_push_event(self, event, spec=None, record=None,
                          timestamp_ns=None, rank=None, request_ids=None,
                          push_metadata=None):
        if self.push_event_stream is None:
            return
        if record is not None:
            request_ids = tuple(record.get("request_ids", ()) or ())
            flow_id = record.get("flow_id")
            src = record.get("src")
            dst = record.get("dst")
            size = record.get("bytes")
            epoch = record.get("push_epoch")
            start_tokens = record.get("push_start_tokens")
            end_tokens = record.get("push_end_tokens")
            settled_tokens = record.get("push_settled_tokens")
            final = record.get("push_final")
        elif spec is not None:
            request_ids = tuple(getattr(spec, "request_ids", ()) or ())
            flow_id = getattr(spec, "flow_id", None)
            src = getattr(spec, "src", None)
            dst = getattr(spec, "dst", None)
            size = getattr(spec, "bytes", None)
            epoch = getattr(spec, "push_epoch", None)
            start_tokens = getattr(spec, "push_start_tokens", None)
            end_tokens = getattr(spec, "push_end_tokens", None)
            settled_tokens = getattr(spec, "push_settled_tokens", None)
            final = getattr(spec, "push_final", None)
        else:
            request_ids = tuple(request_ids or ())
            flow_id = src = dst = size = None
            push_metadata = push_metadata or {}
            epoch = push_metadata.get("push_epoch")
            start_tokens = push_metadata.get("push_start_tokens")
            end_tokens = push_metadata.get("push_end_tokens")
            settled_tokens = push_metadata.get("push_settled_tokens")
            final = push_metadata.get("push_final")
        if request_ids is not None:
            request_ids = tuple(request_ids)
        if not request_ids:
            return
        writer = csv.writer(self.push_event_stream)
        for request_id in request_ids:
            state = self.push_states.setdefault(int(request_id), {
                "first_settlement": None, "last_settlement": None,
                "last_write": None, "commit": None,
                "settled_tokens": 0, "posted_tokens": 0,
                "total_bytes": 0, "write_count": 0,
                "commit_rank_count": 0, "settlement_events": set(),
            })
            ts = (int(timestamp_ns) if timestamp_ns is not None else None)
            if settled_tokens is not None:
                value = int(settled_tokens)
                state["settled_tokens"] = max(state["settled_tokens"], value)
                if event == "PUSH_SETTLED":
                    if state["first_settlement"] is None:
                        state["first_settlement"] = ts
                    state["last_settlement"] = ts
            if (end_tokens is not None and
                    event in ("PUSH_WRITE_SUBMITTED", "PUSH_WRITE_COMPLETED")):
                state["posted_tokens"] = max(state["posted_tokens"],
                                             int(end_tokens))
            if event == "PUSH_WRITE_SUBMITTED":
                state["total_bytes"] += int(size or 0)
                state["write_count"] += 1
            if event == "PUSH_WRITE_COMPLETED":
                state["last_write"] = ts
            if event == "PUSH_COMMITTED":
                state["commit"] = ts
                state["commit_rank_count"] += 1
            writer.writerow([
                event, ts, int(request_id), ("" if rank is None else int(rank)),
                ("" if flow_id is None else flow_id),
                ("" if epoch is None else int(epoch)),
                ("" if start_tokens is None else int(start_tokens)),
                ("" if end_tokens is None else int(end_tokens)),
                state["settled_tokens"], ("" if size is None else int(size)),
                ("" if src is None else int(src)),
                ("" if dst is None else int(dst)),
                ("" if final is None else int(final)), "NIXL_PUSH",
            ])
        self.push_event_stream.flush()

    def _write_push_request(self, request_id):
        if self.push_request_stream is None:
            return
        state = self.push_states.get(int(request_id))
        if not state or state.get("request_row_written"):
            return
        writer = csv.writer(self.push_request_stream)
        writer.writerow([
            int(request_id), state.get("first_settlement"),
            state.get("last_settlement"), state.get("last_write"),
            state.get("commit"), state.get("settled_tokens", 0),
            state.get("posted_tokens", 0), state.get("total_bytes", 0),
            state.get("write_count", 0), state.get("commit_rank_count", 0),
        ])
        state["request_row_written"] = True
        self.push_request_stream.flush()

    def _try_push_commit(self, job, request_id, fallback):
        request_id = int(request_id)
        expected_nodes = job["push_write_nodes"].get(request_id, set())
        activated_nodes = job["push_activated_nodes"].get(request_id, set())
        flow_ids = job["push_flow_ids"].get(request_id, set())
        completed = job.setdefault("push_completed_flows", set())
        pending_for_request = any(
            scope[0] == request_id and queue
            for scope, queue in self.push_pending_by_scope.items())
        inflight_for_request = any(
            scope[0] == request_id
            for scope in self.push_inflight_by_scope)
        if (not expected_nodes or not expected_nodes <= activated_nodes or
                pending_for_request or inflight_for_request or
                not flow_ids <= completed):
            return
        finish = max(
            [int(self.network.flow_finish(flow_id) or fallback)
             for flow_id in flow_ids] or [int(fallback)])
        waiters = list(self.push_commit_waiters.pop(
            (int(job["id"]), request_id), set()))
        for waiter_job_id, waiter_key in waiters:
            waiter_job = self.jobs.get(waiter_job_id)
            if waiter_job is None:
                continue
            self._finish_node(waiter_job, waiter_key, finish)
            self._write_push_event(
                "PUSH_COMMITTED", request_ids=(request_id,),
                timestamp_ns=finish, rank=waiter_key[0])
        if not any(int(waiter_request_id) == int(request_id)
                   for _, waiter_request_id in self.push_commit_waiters):
            self._write_push_request(request_id)

    def _submit_push_write(self, job, key, ready, request_id,
                           comm_key, metadata):
        src, dst, tag, size = comm_key
        flow_id = "%d:push:%d:%d:%d:%d:%d" % (
            int(job["id"]), src, dst, tag, size, int(key[1]))
        spec = FlowSpec(
            flow_id, src, dst, size, int(ready), "KV_MOVEMENT",
            "NIXL_PUSH_WRITE", **metadata)
        job["push_flow_ids"].setdefault(request_id, set()).add(flow_id)
        self.push_flow_info[flow_id] = (
            int(job["id"]), request_id, int(key[0]), metadata)
        self.flow_graph[flow_id] = job["id"]
        self.flow_graph_path[flow_id] = job.get("path")
        scope = (int(request_id), int(key[0]))
        self.push_inflight_by_scope[scope] = flow_id
        if flow_id not in self.flow_submitted:
            self.flow_submitted.add(flow_id)
            self._write_push_event(
                "PUSH_WRITE_SUBMITTED", spec=spec,
                timestamp_ns=int(ready), rank=key[0])
            self._write_kv_event(
                "KV_GENERATED", spec=spec, timestamp_ns=int(ready))
            self.network.submit([spec])
        if self.network.flow_finished(flow_id):
            self._complete_flow(flow_id)

    def _start_next_push_write(self, scope):
        queue = self.push_pending_by_scope.get(scope)
        if not queue:
            self.push_pending_by_scope.pop(scope, None)
            return
        job, key, ready, request_id, comm_key, metadata = queue.popleft()
        if not queue:
            self.push_pending_by_scope.pop(scope, None)
        self._submit_push_write(
            job, key, ready, request_id, comm_key, metadata)

    def _activate_push_write(self, job, key, ready):
        record = job["nodes"][key]
        src, dst, tag, size = record["comm_key"]
        request_ids = tuple(record.get("metadata", {}).get("request_ids", ()))
        if len(request_ids) != 1:
            raise RuntimeError("NIXL Push WRITE must identify exactly one request")
        request_id = int(request_ids[0])
        metadata = dict(record.get("metadata", {}))
        job["push_activated_nodes"].setdefault(request_id, set()).add(key)
        scope = (request_id, int(key[0]))
        if scope in self.push_inflight_by_scope:
            self.push_pending_by_scope.setdefault(scope, deque()).append(
                (job, key, int(ready), request_id, record["comm_key"], metadata))
        else:
            self._submit_push_write(
                job, key, int(ready), request_id, record["comm_key"], metadata)
        # A WRITE is a nonblocking producer-side operation. The request-level
        # commit node, not this graph node, carries Decode admission semantics.
        self._finish_node(job, key, int(ready))

    def _activate_push_commit(self, job, key, ready):
        metadata = job["nodes"][key].get("metadata", {})
        request_ids = tuple(metadata.get("request_ids", ()))
        if len(request_ids) != 1:
            raise RuntimeError("NIXL Push COMMIT must identify exactly one request")
        request_id = int(request_ids[0])
        waiter_key = (int(job["id"]), key)
        self.push_commit_waiters.setdefault(
            (int(job["id"]), request_id), set()).add(waiter_key)
        self._try_push_commit(job, request_id, int(ready))


    def _write_collective_event(self, job, collective_key, end_ns):
        if self.collective_event_stream is None:
            return
        keys = job["collective_node_keys"].get(collective_key, ())
        if not keys:
            return
        records = [job["nodes"][key] for key in keys
                   if key in job["nodes"]]
        if not records:
            return
        metadata = [record.get("metadata", {}) for record in records]
        request_ids = sorted({str(request_id)
                              for item in metadata
                              for request_id in item.get("request_ids", ())})
        first = records[0]
        start_ns = int(job["collective_start"].get(collective_key, end_ns))
        node = first["node"]
        row = {
            "event": "COLLECTIVE_COMPLETED",
            "traffic_class": first.get("class"),
            "traffic_subtype": first.get("subtype"),
            "collective_type": _collective_type_name(node),
            "collective_id": _attr(node, "collective_id", None),
            "batch_id": metadata[0].get("batch_id"),
            "collective_batch_id": metadata[0].get("collective_batch_id"),
            "layer_id": metadata[0].get("layer_id"),
            "event_type": metadata[0].get("event_type"),
            "request_ids": request_ids,
            "start_ns": start_ns,
            "end_ns": int(end_ns),
            "cct_ns": max(0, int(end_ns) - start_ns),
            "bytes_per_participant": int(_attr(
                node, "comm_size", 0)),
            "participant_count": len(records),
            "peer_flow_count": int(job["collective_flow_count"].get(
                collective_key, 0)),
        }
        self.collective_event_stream.write(json.dumps(
            row, sort_keys=True) + "\n")

    def _write_ep_p2p_collective(self, job, group, end_ns):
        """Write one CCT row for an A2A_P2P EP round."""
        if self.collective_event_stream is None:
            return
        metadata = job["ep_collective_meta"].get(group, {})
        flow_nodes = job["ep_collective_flow_nodes"].get(group, {})
        flow_bytes = job["ep_collective_flow_bytes"].get(group, {})
        completed_flows = list(job["ep_collective_completed_flows"].get(
            group, ()))
        start_ns = int(job["ep_collective_start"].get(group, end_ns))
        expected = job["ep_collective_expected_nodes"].get(group, set())
        row = {
            "event": "COLLECTIVE_COMPLETED",
            "traffic_class": "EP",
            "traffic_subtype": metadata.get("traffic_subtype", "EP"),
            "collective_type": "A2A_P2P",
            "collective_id": metadata.get("collective_id"),
            "batch_id": metadata.get("batch_id"),
            "collective_batch_id": metadata.get("collective_batch_id"),
            "layer_id": metadata.get("layer_id"),
            "event_type": metadata.get("event_type"),
            "request_ids": sorted({str(item) for item in metadata.get(
                "request_ids", ())}),
            "start_ns": start_ns,
            "end_ns": int(end_ns),
            "cct_ns": max(0, int(end_ns) - start_ns),
            "bytes_sum": sum(flow_bytes.values()),
            "bytes_max_flow": max(flow_bytes.values(), default=0),
            "participant_flow_count": int(job["ep_collective_flow_count"].get(
                group, 0)),
            "participant_node_count": len(expected),
            "round_id": "%s:%s" % (job["id"], metadata.get("collective_id")),
        }
        if completed_flows:
            ordered = sorted(completed_flows, key=lambda item: (
                int(item.get("end_ns", end_ns)), str(item.get("flow_id"))))
            critical_end = max(int(item.get("end_ns", end_ns))
                               for item in ordered)
            critical = [item for item in ordered
                        if int(item.get("end_ns", end_ns)) == critical_end]
            critical_bytes = sum(int(item.get("bytes", 0)) for item in critical)
            row.update({
                "flow_count": len(ordered),
                "critical_flow_count": len(critical),
                "critical_flow_bytes": critical_bytes,
                "critical_flow_fraction": (
                    critical_bytes / float(sum(int(item.get("bytes", 0))
                                               for item in ordered))
                    if ordered else 0.0),
                "critical_flow_ids": [item.get("flow_id") for item in critical],
            })
            ep_detail_start = max(
                0, int(os.environ.get(
                    "FLOWSIM_EP_FLOW_TELEMETRY_START_NS", "0")))
            ep_detail_end_text = os.environ.get(
                "FLOWSIM_EP_FLOW_TELEMETRY_END_NS")
            ep_detail_end = (None if ep_detail_end_text in (None, "")
                             else int(ep_detail_end_text))
            if (self.ep_flow_event_stream is not None and
                    int(end_ns) >= ep_detail_start and
                    (ep_detail_end is None or start_ns <= ep_detail_end)):
                for rank, item in enumerate(ordered, start=1):
                    detail = dict(item)
                    detail.update({
                        "event": "EP_FLOW_COMPLETED",
                        "traffic_class": "EP",
                        "round_id": row["round_id"],
                        "collective_id": metadata.get("collective_id"),
                        "layer_id": metadata.get("layer_id"),
                        "event_type": metadata.get("event_type"),
                        "request_ids": row["request_ids"],
                        "collective_start_ns": start_ns,
                        "collective_end_ns": int(end_ns),
                        "collective_cct_ns": row["cct_ns"],
                        "completion_rank": rank,
                        "is_last_completing": int(item.get("end_ns", end_ns)) == critical_end,
                        "queueing_ns": max(
                            0, int(item.get("start_ns", start_ns)) -
                            int(item.get("requested_start_ns", start_ns))),
                    })
                    if (self.ep_flow_telemetry_link_ids and
                            not (set(detail.get("path", ())) &
                                 self.ep_flow_telemetry_link_ids)):
                        continue
                    if (not self.max_ep_flow_telemetry_rows or
                            self.ep_flow_telemetry_rows <
                            self.max_ep_flow_telemetry_rows):
                        self.ep_flow_event_stream.write(
                            json.dumps(detail, sort_keys=True) + "\n")
                        self.ep_flow_telemetry_rows += 1
        self.collective_event_stream.write(json.dumps(
            row, sort_keys=True) + "\n")

    def _debug(self, event, **fields):
        debug_events = os.environ.get("FLOWSIM_EXEC_DEBUG_EVENTS")
        if (debug_events and event not in {
                item.strip() for item in debug_events.split(",")
                if item.strip()}):
            return
        if not self.debug_path or self.debug_count >= int(
                os.environ.get("FLOWSIM_EXEC_DEBUG_LIMIT", "512")):
            return
        self.debug_count += 1
        row = {"event": event, **fields}
        with open(self.debug_path, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")

    def _write_flow_telemetry(self, flow_id):
        if flow_id in self.telemetry_written:
            return
        record = self.network.flow_record(flow_id)
        if record is None:
            return
        self.telemetry_written.add(flow_id)
        if record.get("traffic_class") not in self.telemetry_classes:
            release = getattr(self.network, "release_flow_record", None)
            if release is not None:
                release(flow_id)
            return
        row = dict(record)
        row["graph_id"] = self.flow_graph.get(flow_id)
        row["graph_path"] = self.flow_graph_path.get(flow_id)
        row["request_ids"] = list(row.get("request_ids", ()) or ())
        if (self.write_flow_telemetry and self.telemetry_path and
                (not self.max_flow_telemetry_rows or
                 self.flow_telemetry_rows < self.max_flow_telemetry_rows)):
            with open(self.telemetry_path, "a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, sort_keys=True) + "\n")
            self.flow_telemetry_rows += 1
        release = getattr(self.network, "release_flow_record", None)
        if release is not None:
            release(flow_id)

    def _retire_flow_state(self, flow_id, keep_completed=False):
        """Bound per-flow executor/backend state after graph completion.

        A P2D sender may finish before its paired receiver graph is
        activated.  Such a flow is retained until the receiver consumes the
        FIFO entry in ``p2d_unpaired_flows``.  Decode EP and other flows have
        no late waiter and can be retired immediately.  This is lifecycle
        bookkeeping only; it does not alter network rates or timestamps.
        """
        if keep_completed:
            return
        self.flow_submitted.discard(flow_id)
        self.telemetry_written.discard(flow_id)
        retire = getattr(self.network, "retire_flow", None)
        if retire is not None:
            retire(flow_id)

    @staticmethod
    def _node_key(rank, node_id):
        return int(rank), int(node_id)

    def submit(self, now_ns, graph_items, graph_id, graph_path=None):
        Node, GlobalMetadata, send_type, recv_type, coll_type, _, _ = _chakra_imports()
        del Node, GlobalMetadata
        job = {
            "id": int(graph_id),
            "path": graph_path,
            "ranks": [int(rank) for rank, _ in graph_items],
            "start_ns": int(now_ns),
            "nodes": {},
            "children": {},
            "unresolved": {},
            "activated": set(),
            "node_finish": {},
            "node_flow_pending": {},
            "collective_members": {},
            "collective_started": set(),
            "collective_flow_pending": {},
            "collective_node_keys": {},
            "collective_finish": {},
            "collective_start": {},
            "collective_flow_count": {},
            "ep_collective_expected_nodes": {},
            "ep_collective_completed_nodes": {},
            "ep_collective_flow_nodes": {},
            "ep_collective_flow_bytes": {},
            "ep_collective_completed_flows": {},
            "ep_collective_flow_count": {},
            "ep_collective_seen_flows": {},
            "ep_collective_start": {},
            "ep_collective_end": {},
            "ep_collective_meta": {},
            "comm_flow_by_key": {},
            "remote_prefetch_ready": {},
            "push_write_nodes": {},
            "push_activated_nodes": {},
            "push_flow_ids": {},
            "push_completed_flows": set(),
            "push_commit_nodes": {},
            "completed": False,
        }
        for rank, nodes in graph_items:
            rank = int(rank)
            for node in sorted(nodes, key=lambda item: int(item.id)):
                key = self._node_key(rank, node.id)
                parents = [
                    self._node_key(rank, parent)
                    for parent in node.data_deps
                ]
                parents = [parent for parent in parents
                           if parent in job["nodes"]]
                kind = "compute"
                if node.type in (send_type, recv_type):
                    kind = "p2p"
                elif node.type == coll_type:
                    kind = "collective"
                traffic_class, traffic_subtype = _phase_class(node.name, node)
                # Prefill MoE communication is not Decode-side EP.  Keep it
                # as OTHER so EP_FIRST protects only the latency-sensitive
                # Decode collective in a P/D run.  In a colocated/non-PD run
                # decode_ranks is None and all model EP communication remains
                # classified as EP.
                if (traffic_class == "EP" and self.decode_ranks is not None
                        and rank not in self.decode_ranks):
                    traffic_class = "OTHER"
                    traffic_subtype = "PREFILL_EP"
                record = {
                    "key": key,
                    "node": node,
                    "kind": kind,
                    "parents": parents,
                    "duration_ns": int(node.duration_micros) * 1000,
                    "class": traffic_class,
                    "subtype": traffic_subtype,
                    "event_type": _attr(node, "event_type", None),
                    "is_send": node.type == send_type,
                }
                if kind == "p2p":
                    record["comm_key"] = (
                        int(_attr(node, "comm_src", rank)),
                        int(_attr(node, "comm_dst", rank)),
                        int(_attr(node, "comm_tag", int(node.id))),
                        int(_attr(node, "comm_size", 0)),
                    )
                    record["metadata"] = _flow_metadata(node)
                elif kind == "collective":
                    collective_id = _attr(node, "collective_id", None)
                    record["collective_key"] = (
                        collective_id if collective_id is not None else node.name)
                    record["metadata"] = _flow_metadata(node, record["collective_key"])
                else:
                    # Zero-time NIXL Push COMMIT nodes are represented as
                    # compute/control nodes, but still carry request-scoped
                    # metadata needed by the final barrier.
                    record["metadata"] = _flow_metadata(node)
                job["nodes"][key] = record
                job["unresolved"][key] = len(parents)
                job["children"].setdefault(key, [])
                for parent in parents:
                    job["children"].setdefault(parent, []).append(key)
        for key, record in job["nodes"].items():
            metadata = record.get("metadata", {})
            request_ids = metadata.get("request_ids", ())
            event_type = metadata.get("event_type")
            for request_id in request_ids:
                request_id = int(request_id)
                if event_type == 4 and record.get("is_send"):
                    job["push_write_nodes"].setdefault(request_id, set()).add(key)
                elif event_type == 5:
                    job["push_commit_nodes"].setdefault(request_id, set()).add(key)
            if record["kind"] != "p2p" or record["class"] != "EP":
                continue
            collective_id = record.get("metadata", {}).get("collective_id")
            if collective_id is None:
                continue
            group = ("EP_P2P", collective_id)
            job["ep_collective_expected_nodes"].setdefault(
                group, set()).add(key)
            job["ep_collective_completed_nodes"].setdefault(group, set())
            job["ep_collective_flow_nodes"].setdefault(group, {})
        self.jobs[job["id"]] = job
        self._prepare_remote_prefix_fetches(job, int(now_ns))
        self._debug(
            "submit", graph_id=int(graph_id), now_ns=int(now_ns),
            nodes=len(job["nodes"]), p2p=sum(
                item["kind"] == "p2p" for item in job["nodes"].values()),
            collective=sum(
                item["kind"] == "collective"
                for item in job["nodes"].values()),
            decode_ranks=sorted(self.decode_ranks or ()),
            local_next=(self.local_events[0][0]
                        if self.local_events else None),
            network_next=self.network.next_event_time())
        if not job["nodes"]:
            job["completed"] = True
            return
        for key, count in job["unresolved"].items():
            if count == 0:
                self._activate(job, key, int(now_ns))
        self._finish_empty_job(job)

    def _prepare_remote_prefix_fetches(self, job, now_ns):
        """Submit R->P fetches before suffix Prefill compute in B1 mode."""
        if self.remote_kv_mode not in (
                'REMOTE_PREFIX_PD_BASELINE',
                'SPLIT_SOURCE_KV_ASSEMBLY'):
            return
        request_ids = set()
        for record in job["nodes"].values():
            if record["class"] == "KV_MOVEMENT" and record["subtype"] == "P2D":
                request_ids.update(record.get("metadata", {}).get("request_ids", ()))
        if not request_ids:
            return
        first_compute = {}
        last_p2d = {}
        for key, record in job["nodes"].items():
            if record["kind"] == "compute":
                first_compute.setdefault(int(key[0]), key)
            if (record["kind"] == "p2p" and
                    record["class"] == "KV_MOVEMENT" and
                    record["subtype"] == "P2D"):
                for request_id in record.get("metadata", {}).get(
                        "request_ids", ()):
                    request_id = int(request_id)
                    previous = last_p2d.get(request_id)
                    if previous is None or key > previous:
                        last_p2d[request_id] = key
        prefill_waiters = list(first_compute.values())
        if not prefill_waiters:
            raise RuntimeError(
                "REMOTE_PREFIX_PD_BASELINE graph has no Prefill compute node")
        for request_id in sorted(int(value) for value in request_ids):
            plan = self.remote_kv_plan.get(str(request_id))
            if not plan or request_id in self.remote_kv_submitted:
                continue
            decode_waiter = last_p2d.get(request_id)
            if (self.remote_kv_mode == 'SPLIT_SOURCE_KV_ASSEMBLY' and
                    decode_waiter is None):
                raise RuntimeError(
                    "SPLIT_SOURCE_KV_ASSEMBLY request %d has no P2D barrier node"
                    % request_id)
            for index, item in enumerate(plan.get("fetches", ())):
                src = int(item["src"])
                dst = int(item["dst"])
                size = int(item["bytes"])
                if size <= 0 or src == dst:
                    continue
                role = str(item.get("role", "REMOTE_KV_TO_PREFILL"))
                if (self.remote_kv_mode == 'REMOTE_PREFIX_PD_BASELINE' or
                        role == "REMOTE_KV_TO_PREFILL"):
                    waiter_keys = prefill_waiters
                    subtype = "REMOTE_KV_TO_PREFILL"
                elif role == "REMOTE_KV_TO_DECODE":
                    waiter_keys = [decode_waiter]
                    subtype = "REMOTE_KV_TO_DECODE"
                else:
                    raise RuntimeError(
                        "unknown split-source remote KV role %s" % role)
                block_index = int(item.get("block_index", index))
                flow_id = "remote_prefix:%s:%d:%d:%d:%d:%d" % (
                    subtype, request_id, block_index, src, dst, size)
                spec = FlowSpec(
                    flow_id, src, dst, size, int(now_ns),
                    "KV_MOVEMENT", subtype,
                    request_ids=(request_id,),
                    batch_id=None, layer_id=item.get("layer_id"), event_type=1)
                self._register_flow(
                    job, flow_id, spec, waiter_keys, submit=False)
                if flow_id in self.flow_submitted:
                    continue
                if not self.replica_warmup_flow_ids:
                    self.replica_warmup_complete = True
                    self.flow_submitted.add(flow_id)
                    self._write_kv_event(
                        "KV_GENERATED", spec=spec, timestamp_ns=int(now_ns))
                    self.network.submit([spec])
                else:
                    self.remote_kv_pending_specs.append(spec)
            self.remote_kv_submitted.add(request_id)

    def _finish_empty_job(self, job):
        if job["completed"]:
            return
        if len(job["node_finish"]) == len(job["nodes"]):
            job["completed"] = True

    @staticmethod
    def _ready_time(job, record, fallback):
        if not record["parents"]:
            return int(fallback)
        return max(
            int(job["node_finish"].get(parent, fallback))
            for parent in record["parents"])

    def _schedule_compute(self, job, key, ready):
        record = job["nodes"][key]
        finish = int(ready) + int(record["duration_ns"])
        self.sequence += 1
        heapq.heappush(self.local_events,
                       (finish, self.sequence, job["id"], key))

    def _register_flow(self, job, flow_id, spec, node_keys, submit=True):
        waiters = self.flow_waiters.setdefault(flow_id, set())
        for key in node_keys:
            waiters.add((job["id"], key))
            job["node_flow_pending"].setdefault(key, set()).add(flow_id)
        self.flow_graph.setdefault(flow_id, job["id"])
        self.flow_graph_path.setdefault(flow_id, job.get("path"))
        for key in node_keys:
            node_record = job["nodes"].get(key)
            metadata = node_record.get("metadata", {}) if node_record else {}
            if (node_record is None or node_record["class"] != "EP" or
                    metadata.get("collective_id") is None):
                continue
            group = ("EP_P2P", metadata["collective_id"])
            job["ep_collective_flow_nodes"].setdefault(
                group, {}).setdefault(flow_id, set()).add(key)
            job["ep_collective_flow_bytes"].setdefault(
                group, {})[flow_id] = int(spec.bytes)
            seen = job["ep_collective_seen_flows"].setdefault(group, set())
            if flow_id not in seen:
                seen.add(flow_id)
                job["ep_collective_flow_count"][group] = (
                    int(job["ep_collective_flow_count"].get(group, 0)) + 1)
            self.ep_p2p_flow_groups.setdefault(flow_id, set()).add(
                (job["id"], group))
            start = int(spec.start_ns)
            previous = job["ep_collective_start"].get(group)
            job["ep_collective_start"][group] = (
                start if previous is None else min(previous, start))
            job["ep_collective_meta"].setdefault(group, metadata)
        if submit and flow_id not in self.flow_submitted:
            self.flow_submitted.add(flow_id)
            self._debug(
                "network_submit", flow_id=flow_id,
                requested_start=int(spec.start_ns),
                network_clock=int(self.network.clock_ns),
                traffic_class=spec.traffic_class,
                subtype=spec.traffic_subtype)
            if spec.traffic_class == "KV_MOVEMENT":
                # Graph readiness is the model-derived KV generation point.
                # Actual network release is emitted by the persistent backend
                # after optional finite-buffer admission, so a sensitivity run
                # cannot mistake staged bytes for transmitted bytes.
                self._write_kv_event(
                    "KV_GENERATED", spec=spec,
                    timestamp_ns=int(spec.start_ns))
            self.network.submit([spec])
        if self.network.flow_finished(flow_id):
            self._complete_flow(flow_id)

    def _new_p2d_flow(self, job, key, record, ready, comm_key,
                      extra_waiters=()):
        """Create one request-scoped P2D flow and attach its graph nodes."""
        src, dst, tag, size = comm_key
        flow_id = "%d:p2d:%d:%d:%d:%d:%d" % (
            job["id"], src, dst, tag, size, key[1])
        spec = FlowSpec(flow_id, src, dst, size, int(ready),
                        record["class"], record["subtype"],
                        **record.get("metadata", {}))
        node_waiters = [(job["id"], key)]
        node_waiters.extend(extra_waiters)
        for waiter_job_id, waiter_key in node_waiters:
            waiter_job = self.jobs.get(waiter_job_id)
            if waiter_job is None:
                continue
            waiter_job["comm_flow_by_key"][comm_key] = flow_id
        self._register_flow(job, flow_id, spec, [key])
        self._attach_remote_kv_fetches(job, key, record, ready)
        for waiter_job_id, waiter_key in node_waiters[1:]:
            waiter_job = self.jobs.get(waiter_job_id)
            if waiter_job is None:
                continue
            self._register_flow(
                waiter_job, flow_id,
                FlowSpec(flow_id, src, dst, size, int(ready),
                         waiter_job["nodes"][waiter_key]["class"],
                         waiter_job["nodes"][waiter_key]["subtype"],
                         **waiter_job["nodes"][waiter_key].get("metadata", {})),
                [waiter_key])
        return flow_id

    def _attach_remote_kv_fetches(self, job, key, record, ready):
        """Attach legacy direct remote fetches to the P2D graph barrier."""
        if self.remote_kv_mode == 'REMOTE_PREFIX_PD_BASELINE':
            return
        metadata = record.get("metadata", {})
        for request_id in metadata.get("request_ids", ()):
            request_id = int(request_id)
            plan = self.remote_kv_plan.get(str(request_id))
            if not plan or request_id in self.remote_kv_submitted:
                continue
            for index, item in enumerate(plan.get("fetches", ())):
                src = int(item["src"])
                dst = int(item["dst"])
                size = int(item["bytes"])
                if size <= 0 or src == dst:
                    continue
                block_index = int(item.get("block_index", index))
                flow_id = "remote_kv:%d:%d:%d:%d:%d" % (
                    request_id, block_index, src, dst, size)
                spec = FlowSpec(
                    flow_id, src, dst, size, int(ready),
                    "KV_MOVEMENT", "REMOTE_KV_FETCH",
                    request_ids=(request_id,),
                    batch_id=metadata.get("batch_id"),
                    layer_id=item.get("layer_id"), event_type=1)
                self._register_flow(job, flow_id, spec, [key], submit=False)
                if flow_id not in self.flow_submitted:
                    if not self.replica_warmup_flow_ids:
                        self.replica_warmup_complete = True
                        self.flow_submitted.add(flow_id)
                        self._write_kv_event(
                            "KV_GENERATED", spec=spec,
                            timestamp_ns=int(ready))
                        self.network.submit([spec])
                    else:
                        self.remote_kv_pending_specs.append(spec)
            self.remote_kv_submitted.add(request_id)

    def _activate_p2p(self, job, key, ready):
        record = job["nodes"][key]
        # TP and prefill-side auxiliary communication is outside this study's
        # scale-out fabric. Complete it at the DAG-ready timestamp so it does
        # not consume FlowSim state or contend with Decode EP. Opt in to the
        # legacy all-traffic model with FLOWSIM_NETWORK_CLASSES=...
        if record["class"] not in self.network_classes:
            self._finish_node(job, key, int(ready))
            return
        comm_key = record["comm_key"]
        flow_id = job["comm_flow_by_key"].get(comm_key)
        # In ACTUAL P/D mode the receiver graph is dispatched before the
        # Prefill sender graph.  It must wait for the sender's model-compute
        # completion; otherwise merely observing a receiver creates a P2D
        # flow at time zero and removes the transfer from TTFT's critical path.
        if (flow_id is None and record["subtype"] == "P2D" and
                not record["is_send"]):
            pending = self.p2d_unpaired_flows.get(comm_key)
            if pending:
                flow_id = pending.popleft()
                if not pending:
                    del self.p2d_unpaired_flows[comm_key]
                self.p2d_unpaired_flow_ids.discard(flow_id)
                job["comm_flow_by_key"][comm_key] = flow_id
                self._register_flow(
                    job, flow_id,
                    FlowSpec(flow_id, comm_key[0], comm_key[1], comm_key[3],
                             int(ready), record["class"], record["subtype"],
                             **record.get("metadata", {})),
                    [key])
                if self.network.flow_finished(flow_id):
                    self._retire_flow_state(flow_id)
            else:
                self.p2d_waiters.setdefault(comm_key, deque()).append(
                    (job["id"], key))
            return
        if flow_id is None:
            src, dst, tag, size = comm_key
            if record["subtype"] == "P2D":
                waiters = self.p2d_waiters.get(comm_key)
                waiter = waiters.popleft() if waiters else None
                if waiters is not None and not waiters:
                    del self.p2d_waiters[comm_key]
                extra = [waiter] if waiter is not None else []
                flow_id = self._new_p2d_flow(
                    job, key, record, ready, comm_key, extra)
                if waiter is None:
                    self.p2d_unpaired_flows.setdefault(
                        comm_key, deque()).append(flow_id)
                    self.p2d_unpaired_flow_ids.add(flow_id)
            else:
                flow_id = "%d:p2p:%d:%d:%d:%d:%d" % (
                    job["id"], src, dst, tag, size, key[1])
                job["comm_flow_by_key"][comm_key] = flow_id
                spec = FlowSpec(flow_id, src, dst, size, int(ready),
                                record["class"], record["subtype"],
                                **record.get("metadata", {}))
                self._register_flow(job, flow_id, spec, [key])
        else:
            job["comm_flow_by_key"][comm_key] = flow_id
            self._register_flow(
                job, flow_id,
                FlowSpec(flow_id, comm_key[0], comm_key[1], comm_key[3],
                         int(ready), record["class"], record["subtype"],
                         **record.get("metadata", {})),
                [key])

    def _start_collective(self, job, collective_key):
        if collective_key in job["collective_started"]:
            return
        members = job["collective_members"].get(collective_key, [])
        if not members:
            return
        job["collective_started"].add(collective_key)
        participants = sorted({key[0] for key, _ in members})
        ready = max(ready for _, ready in members)
        if all(item["class"] not in self.network_classes
               for key, _ in members
               for item in [job["nodes"][key]]):
            for key, _ in members:
                self._finish_node(job, key, ready)
            return
        if len(participants) < 2:
            for key, _ in members:
                self._finish_node(job, key, ready)
            return
        # All participant nodes have the same collective-level dependency:
        # they become ready only after the last generated peer flow finishes.
        # Keep this as one barrier instead of inserting every member key into
        # every flow's waiter set.  This is especially important for EP64,
        # where a 64-way peer matrix is generated for every MoE layer.
        pending_flows = set()
        job["collective_flow_pending"][collective_key] = pending_flows
        job["collective_node_keys"][collective_key] = [
            key for key, _ in members]
        job["collective_finish"][collective_key] = int(ready)
        job["collective_start"][collective_key] = int(ready)
        job["collective_flow_count"][collective_key] = 0
        all_flow_ids = []
        for key, _ in members:
            record = job["nodes"][key]
            size = int(_attr(record["node"], "comm_size", 0))
            per_peer = _collective_peer_bytes(
                record["node"], size, len(participants))
            for dst in participants:
                if dst == key[0]:
                    continue
                flow_id = "%d:coll:%s:%d:%d" % (
                    job["id"], str(collective_key), key[0], dst)
                metadata = dict(record.get("metadata", {}))
                metadata["collective_type"] = _collective_type_name(
                    record["node"])
                spec = FlowSpec(
                    flow_id, key[0], dst, per_peer, int(ready),
                    record["class"], record["subtype"], **metadata)
                pending_flows.add(flow_id)
                job["collective_flow_count"][collective_key] += 1
                self.collective_flow_barriers[flow_id] = (
                    job["id"], collective_key)
                self._register_flow(job, flow_id, spec,
                                    [])
                all_flow_ids.append(flow_id)
        if not all_flow_ids:
            for key, _ in members:
                self._finish_node(job, key, ready)

    def _activate(self, job, key, fallback):
        if key in job["activated"] or key in job["node_finish"]:
            return
        record = job["nodes"][key]
        job["activated"].add(key)
        ready = self._ready_time(job, record, fallback)
        if record.get("event_type") == 4:
            if record.get("is_send"):
                self._activate_push_write(job, key, ready)
            else:
                # FlowSim uses the sender as the authoritative physical
                # transfer; a generated receiver ET node is a compatibility
                # artifact and must not duplicate the write.
                self._finish_node(job, key, int(ready))
        elif record.get("event_type") == 5:
            self._activate_push_commit(job, key, ready)
        elif record.get("event_type") == 6:
            metadata = record.get("metadata", {})
            request_ids = tuple(metadata.get("request_ids", ()))
            if len(request_ids) != 1:
                raise RuntimeError(
                    "NIXL Push SETTLED marker must identify exactly one request")
            self._write_push_event(
                "PUSH_SETTLED", timestamp_ns=int(ready), rank=key[0],
                request_ids=request_ids, push_metadata=metadata)
            self._finish_node(job, key, int(ready))
        elif record["kind"] == "compute":
            pending = job["node_flow_pending"].get(key, set())
            if pending:
                return
            ready = max(int(ready), int(job["remote_prefetch_ready"].pop(key, ready)))
            self._schedule_compute(job, key, ready)
        elif record["kind"] == "p2p":
            self._activate_p2p(job, key, ready)
        else:
            group = record["collective_key"]
            job["collective_members"].setdefault(group, []).append((key, ready))
            members = job["collective_members"][group]
            expected = [item for item in job["nodes"].values()
                        if item["kind"] == "collective" and
                        item["collective_key"] == group]
            if len(members) == len(expected):
                self._start_collective(job, group)

    def _finish_node(self, job, key, finish):
        if key in job["node_finish"]:
            return
        job["node_finish"][key] = int(finish)
        for child in job["children"].get(key, []):
            job["unresolved"][child] -= 1
            if job["unresolved"][child] == 0:
                self._activate(job, child, int(finish))
        self._finish_empty_job(job)

    def _complete_flow(self, flow_id):
        finish = self.network.flow_finish(flow_id)
        if finish is None:
            return
        record = self.network.flow_record(flow_id)
        if flow_id in self.replica_warmup_flow_ids:
            self.replica_warmup_flow_ids.discard(flow_id)
            if not self.replica_warmup_flow_ids:
                self.replica_warmup_complete = True
                self._release_pending_remote_kv()
        push_info = self.push_flow_info.get(flow_id)
        if push_info is not None:
            job_id, request_id, rank, metadata = push_info
            job = self.jobs.get(job_id)
            if job is not None:
                job.setdefault("push_completed_flows", set()).add(flow_id)
            if record is not None:
                self._write_push_event(
                    "PUSH_WRITE_COMPLETED", record=record,
                    timestamp_ns=record.get("end_ns"), rank=rank)
            scope = (int(request_id), int(rank))
            if self.push_inflight_by_scope.get(scope) == flow_id:
                self.push_inflight_by_scope.pop(scope, None)
            self.push_flow_info.pop(flow_id, None)
            self._start_next_push_write(scope)
            if job is not None:
                self._try_push_commit(job, request_id, int(finish))
            # A request can have one final commit waiter per producer rank.
            # The last WRITE may belong to a different job/rank than an
            # already-complete waiter, so re-check every waiter for this
            # request whenever any producer flow completes.
            for (waiter_job_id, waiter_request_id) in list(
                    self.push_commit_waiters):
                if int(waiter_request_id) != int(request_id):
                    continue
                waiter_job = self.jobs.get(int(waiter_job_id))
                if waiter_job is not None:
                    self._try_push_commit(
                        waiter_job, request_id, int(finish))
        if record is not None and record.get("traffic_class") == "KV_MOVEMENT":
            self._write_kv_event(
                "KV_STARTED", record=record,
                timestamp_ns=record.get("start_ns"))
            self._write_kv_event(
                "KV_COMPLETED", record=record,
                timestamp_ns=record.get("end_ns"))
        self._write_flow_telemetry(flow_id)
        for job_id, key in list(self.flow_waiters.get(flow_id, ())):
            job = self.jobs.get(job_id)
            if job is None:
                continue
            pending = job["node_flow_pending"].setdefault(key, set())
            pending.discard(flow_id)
            if not pending:
                node_record = job["nodes"].get(key)
                if node_record is not None and node_record["kind"] == "compute":
                    if key in job["activated"]:
                        self._schedule_compute(job, key, int(finish))
                    else:
                        job["remote_prefetch_ready"][key] = int(finish)
                else:
                    self._finish_node(job, key, int(finish))
        barrier = self.collective_flow_barriers.pop(flow_id, None)
        if barrier is not None:
            job_id, collective_key = barrier
            job = self.jobs.get(job_id)
            if job is not None:
                pending = job["collective_flow_pending"].get(collective_key)
                if pending is not None:
                    pending.discard(flow_id)
                    job["collective_finish"][collective_key] = max(
                        int(job["collective_finish"].get(collective_key, finish)),
                        int(finish))
                    if not pending:
                        collective_finish = job["collective_finish"][collective_key]
                        self._write_collective_event(
                            job, collective_key, collective_finish)
                        for key in job["collective_node_keys"].get(
                                collective_key, ()):
                            self._finish_node(
                                job, key, int(collective_finish))
                        job["collective_flow_pending"].pop(
                            collective_key, None)
                        job["collective_node_keys"].pop(
                            collective_key, None)
                        job["collective_finish"].pop(
                            collective_key, None)
                        job["collective_start"].pop(
                            collective_key, None)
                        job["collective_flow_count"].pop(
                            collective_key, None)
        for job_id, group in self.ep_p2p_flow_groups.pop(flow_id, ()):
            job = self.jobs.get(job_id)
            if job is None:
                continue
            if record is not None:
                job["ep_collective_completed_flows"].setdefault(
                    group, []).append(dict(record))
            flow_nodes = job["ep_collective_flow_nodes"].get(group, {})
            completed_nodes = job["ep_collective_completed_nodes"].setdefault(
                group, set())
            completed_nodes.update(flow_nodes.pop(flow_id, set()))
            if job["ep_collective_expected_nodes"].get(group, set()) <= completed_nodes:
                job["ep_collective_end"][group] = int(finish)
                self._write_ep_p2p_collective(job, group, int(finish))
                job["ep_collective_expected_nodes"].pop(group, None)
                job["ep_collective_completed_nodes"].pop(group, None)
                job["ep_collective_flow_nodes"].pop(group, None)
                job["ep_collective_flow_bytes"].pop(group, None)
                job["ep_collective_completed_flows"].pop(group, None)
                job["ep_collective_flow_count"].pop(group, None)
                job["ep_collective_seen_flows"].pop(group, None)
                job["ep_collective_start"].pop(group, None)
                job["ep_collective_meta"].pop(group, None)
        # The compact finish timestamp remains in FlowSim for late waiters;
        # the executor-side waiter/path metadata is no longer needed after all
        # currently attached graph nodes have been released.
        self.flow_waiters.pop(flow_id, None)
        self.flow_graph.pop(flow_id, None)
        self.flow_graph_path.pop(flow_id, None)
        # Keep a completed P2D flow only when its paired receiver has not yet
        # been activated.  All EP flows can be retired here, which prevents
        # EP64 integrated runs from accumulating hundreds of thousands of
        # completed flow IDs in Python memory.
        keep_completed = False
        if record is not None and record.get("traffic_class") == "KV_MOVEMENT":
            keep_completed = flow_id in self.p2d_unpaired_flow_ids
        self._retire_flow_state(flow_id, keep_completed=keep_completed)

    def flush_link_telemetry(self):
        """Persist bounded residual-fluid link samples for integrated runs.

        ``PersistentFluidFlowNetwork`` already collects bounded link samples
        while advancing the shared fabric, but the interactive worker
        historically only wrote completed-flow records.  Keep the two files
        separate so existing flow readers do not mistake link samples for
        flows.  The samples remain analytical residual-fluid backlog, not
        packet-buffer occupancy or ECN/PFC telemetry.
        """
        rows = getattr(self.network, "telemetry", None)
        if self.telemetry_path and rows:
            parent = os.path.dirname(self.telemetry_path)
            link_path = os.path.join(parent, "link_telemetry.jsonl")
            with open(link_path, "w", encoding="utf-8") as stream:
                stream.write(
                    "# FlowSim residual fluid link telemetry; queue_bytes is "
                    "analytical backlog, not packet queue\n")
                for row in rows:
                    record = dict(row)
                    record["record_type"] = "link_timeseries"
                    stream.write(json.dumps(record, sort_keys=True) + "\n")
            if getattr(self.network, "telemetry_truncated", False):
                with open(link_path, "a", encoding="utf-8") as stream:
                    stream.write(json.dumps({
                        "record_type": "metadata",
                        "telemetry_truncated": True,
                        "max_rows": int(getattr(
                            self.network, "max_telemetry_rows", 0)),
                        "telemetry_truncated_at_ns": getattr(
                            self.network, "telemetry_truncated_at_ns", None),
                    }, sort_keys=True) + "\n")
        if self.kv_event_stream is not None:
            self.kv_event_stream.flush()
            self.kv_event_stream.close()
            self.kv_event_stream = None
        if self.collective_event_stream is not None:
            self.collective_event_stream.flush()
            self.collective_event_stream.close()
            self.collective_event_stream = None
        if self.ep_flow_event_stream is not None:
            self.ep_flow_event_stream.flush()
            self.ep_flow_event_stream.close()
            self.ep_flow_event_stream = None
        if self.push_event_stream is not None:
            self.push_event_stream.flush()
            self.push_event_stream.close()
            self.push_event_stream = None
        if self.push_request_stream is not None:
            self.push_request_stream.flush()
            self.push_request_stream.close()
            self.push_request_stream = None

    def _completed_jobs(self):
        completed = []
        for job_id, job in list(self.jobs.items()):
            if not job["completed"]:
                continue
            finish = max(job["node_finish"].values() or [job["start_ns"]])
            completed.append((int(finish), list(job["ranks"]), job_id))
            del self.jobs[job_id]
        return completed

    def next_event_time(self):
        local = self.local_events[0][0] if self.local_events else None
        network = self.network.next_event_time()
        if local is None:
            return network
        if network is None:
            return int(local)
        return min(int(local), int(network))

    def has_pending(self):
        return bool(self.jobs or self.local_events or
                    self.network.next_event_time() is not None)

    def stall_report(self):
        """Return compact DAG state for a no-event control-plane stall."""
        report = []
        for job_id, job in sorted(self.jobs.items()):
            unresolved = [
                key for key in job["nodes"] if key not in job["node_finish"]
            ]
            report.append({
                "job_id": int(job_id),
                "ranks": list(job["ranks"]),
                "nodes": len(job["nodes"]),
                "finished": len(job["node_finish"]),
                "unresolved": [
                    {
                        "key": list(key),
                        "kind": job["nodes"][key]["kind"],
                        "class": job["nodes"][key]["class"],
                        "subtype": job["nodes"][key]["subtype"],
                        "parents": [list(parent) for parent in
                                     job["nodes"][key]["parents"]],
                        "activated": key in job["activated"],
                    }
                    for key in unresolved[:16]
                ],
            })
        return report

    def advance(self):
        """Advance the earliest local-compute or network event."""
        local = self.local_events[0][0] if self.local_events else None
        network = self.network.next_event_time()
        network_state = None
        if network is None and getattr(self.network, "_active", None):
            active = self.network._active
            paths = {flow_id: data["path"]
                     for flow_id, data in active.items()}
            rates = self.network._rates(active, paths)
            network_state = {
                "active": len(active),
                "positive_rate": sum(1 for flow_id in active
                                      if rates.get(flow_id, 0.0) > 0.0),
                "pathless": sum(1 for data in active.values()
                                 if not data["path"]),
                "classes": {
                    name: sum(1 for data in active.values()
                              if data["spec"].traffic_class == name)
                    for name in ("KV_MOVEMENT", "EP", "OTHER")},
            }
        self._debug("advance", local=local, network=network,
                    network_clock=int(self.network.clock_ns),
                    jobs=sorted(self.jobs), network_state=network_state)
        if local is not None and (network is None or local <= network):
            current = int(local)
            while self.local_events and self.local_events[0][0] == current:
                _, _, job_id, key = heapq.heappop(self.local_events)
                job = self.jobs.get(job_id)
                if job is not None:
                    self._finish_node(job, key, current)
        elif network is not None:
            # Do not let a large P2D completion jump over a Decode local
            # compute/collective-release event.  The persistent backend keeps
            # fluid residuals exact when stopped at this boundary.
            advance_until = getattr(self.network, "advance_until", None)
            completed = (advance_until(local) if local is not None
                         else self.network.advance())
            for flow_id in completed:
                self._complete_flow(flow_id)
        elif self.jobs:
            # A non-empty job with no local or network event is a control-plane
            # stall, not a legitimate serving idle period. Keep this
            # diagnostic opt-in so normal runs remain compact.
            stalled = {}
            for job_id, job in self.jobs.items():
                unresolved = [
                    key for key in job["nodes"]
                    if key not in job["node_finish"]
                ]
                stalled[int(job_id)] = {
                    "nodes": len(job["nodes"]),
                    "finished": len(job["node_finish"]),
                    "unresolved": len(unresolved),
                    "sample": [
                        {
                            "key": list(key),
                            "kind": job["nodes"][key]["kind"],
                            "class": job["nodes"][key]["class"],
                            "parents": [list(parent) for parent in
                                        job["nodes"][key]["parents"]],
                        }
                        for key in unresolved[:8]
                    ],
                }
            self._debug("stalled", jobs=stalled)
        return self._completed_jobs()


class Worker:
    def __init__(self, args):
        self.args = args
        # The interactive serving path must retain flows across graph
        # handshakes.  Otherwise a P2D graph is completed and discarded before
        # the next request's Decode EP graph is submitted, making cross-request
        # KV/EP contention impossible to observe in serving TTFT/TPOT/TBT.
        self.network = PersistentFluidFlowNetwork(
            args.topology, args.policy,
            kv_backpressure=args.kv_backpressure,
            kv_buffer_bytes=args.kv_buffer_bytes,
            critical_flow_file=args.critical_flow_file,
            parallel_link_mode=args.parallel_link_mode)
        self.executor = AsyncGraphExecutor(
            self.network, args.telemetry, decode_ranks=args.decode_ranks,
            remote_kv_plan=args.remote_kv_plan,
            remote_kv_mode=args.remote_kv_mode)
        self.network.set_release_callback(self._on_network_release)
        self.decode_ranks = (None if args.decode_ranks is None else
                             {int(rank) for rank in args.decode_ranks})
        self.rank_groups = [set(group) for group in args.rank_groups]
        self.iterations = [0] * args.total_ranks
        self.sleeping = [False] * args.total_ranks
        self.initial_reported = [False] * args.total_ranks
        self.scheduled = [False] * args.total_ranks
        self.events = []
        # A future ``pass <arrival>`` is only a suppression hint.  A real
        # graph completion can change scheduler state before that deadline
        # (most importantly, P2D can admit Decode).  Generation numbers make
        # the already-queued deadline event stale when that happens, instead
        # of delaying Decode until the next request arrival.
        self.wake_generation = [0] * args.total_ranks
        self.wake_pending = [False] * args.total_ranks
        self.wake_urgent = [False] * args.total_ranks
        self.sequence = 0
        self.now = 0
        self.exit = False
        self.graph_counter = 0

    def _on_network_release(self, spec, timestamp_ns):
        if getattr(spec, "traffic_class", None) != "KV_MOVEMENT":
            return
        self.executor._write_kv_event(
            "KV_REQUESTED", spec=spec, timestamp_ns=int(timestamp_ns))

    def _emit(self, rank, wake=False):
        iteration = self.iterations[rank]
        self.executor._debug(
            "emit", rank=int(rank), now_ns=int(self.now), wake=bool(wake),
            sleeping=bool(self.sleeping[rank]),
            scheduled=bool(self.scheduled[rank]),
            pending_wakes=sum(1 for value in self.wake_pending if value))
        print("R %d %d %d 0" % (rank, iteration, int(self.now)), flush=True)
        print("Waiting", flush=True)
        command = sys.stdin.readline()
        if command == "":
            self.exit = True
            return
        self._command(rank, command.strip(), wake=wake)

    def _schedule(self, ranks, command):
        ranks = [int(rank) for rank in ranks]
        paths = _graph_paths(command, ranks)
        graph_items = []
        for rank, path in paths:
            parsed_rank, nodes = _read_graph(path)
            graph_items.append((parsed_rank, nodes))
        self.executor.submit(
            self.now, graph_items, self.graph_counter, graph_path=command)
        self.graph_counter += 1
        for rank in ranks:
            self.sleeping[rank] = False
            self.scheduled[rank] = True
            self.iterations[rank] += 1
        # Installing a single-rank graph is also a scheduler state change. A
        # TP/EP peer may have answered ``pass <arrival>`` while the graph was
        # being assembled; wake only peers in the same physical rank group.
        peers = set()
        for group in self.rank_groups:
            if any(rank in group for rank in ranks):
                peers.update(group)
        peers.difference_update(ranks)
        self._wake_unscheduled_ranks(allowed=peers)

    def _wake_unscheduled_ranks(self, exclude_rank=None, allowed=None):
        """Re-poll idle/deadline-suppressed ranks after explicit state change."""
        targets = []
        for other_rank, is_scheduled in enumerate(self.scheduled):
            if other_rank == exclude_rank or is_scheduled:
                continue
            if allowed is not None and other_rank not in allowed:
                continue
            self.sleeping[other_rank] = False
            self._queue_wake(other_rank, self.now, invalidate=True, urgent=True)
            targets.append(other_rank)
        self.executor._debug(
            "wake", exclude=(None if exclude_rank is None else int(exclude_rank)),
            allowed=(None if allowed is None else sorted(int(x) for x in allowed)),
            targets=targets, now_ns=int(self.now))

    def _queue_wake(self, rank, deadline, invalidate=False, urgent=False):
        """Queue at most one effective wake per rank at a time."""
        if urgent and self.wake_urgent[rank]:
            return
        if not urgent and self.wake_pending[rank]:
            return
        if invalidate:
            self.wake_generation[rank] += 1
        if urgent:
            self.wake_urgent[rank] = True
        self.wake_pending[rank] = True
        self.sequence += 1
        heapq.heappush(
            self.events,
            (int(deadline), self.sequence, rank, True,
             self.wake_generation[rank]))

    def _command(self, rank, command, wake=False):
        self.executor._debug("command", rank=int(rank), command=command,
                    wake=bool(wake), now_ns=int(self.now))
        del wake
        if command == "exit":
            self.exit = True
            return
        if command == "done":
            self.sleeping[rank] = True
            return
        if command.startswith("pass"):
            fields = command.split()
            # HTSim suppresses an ordinary ``pass`` until another rank makes
            # progress.  Re-emitting it at the same timestamp causes an
            # infinite frontend loop, especially while P2D is waiting for a
            # Decode admission.  A future deadline is the only time-based
            # wakeup needed for a normal pass.
            if len(fields) == 1:
                self.sleeping[rank] = True
                return
            deadline = int(fields[1])
            if deadline < 0:
                # The native backend uses ``pass -1`` to invalidate an
                # internal suppression flag.  FlowSim has no such backend
                # flag.  This explicit state-change marker is also used after
                # P2D admission, so invalidate future arrival-deadline polls
                # on other idle ranks here.
                self.sleeping[rank] = True
                self._wake_unscheduled_ranks(
                    exclude_rank=rank, allowed=self.decode_ranks)
            elif deadline > self.now:
                self.sleeping[rank] = False
                self._queue_wake(rank, deadline)
            else:
                self.sleeping[rank] = True
            return
        if command.startswith("group "):
            fields = command.split(maxsplit=2)
            if len(fields) != 3:
                raise ValueError("malformed FlowSim group command: %s" % command)
            ranks = [int(item) for item in fields[2].split(",") if item]
            self._schedule(ranks, fields[1])
            return
        self._schedule([rank], command)

    def run(self):
        # The event handler is a real frontend handshake.  It is intentionally
        # not treated as a request or a network flow.
        for rank in range(self.args.total_ranks):
            if self.scheduled[rank]:
                continue
            self.initial_reported[rank] = True
            self._emit(rank)
            if self.exit:
                return
        while not self.exit:
            # A graph command is nonblocking: its compute/communication DAG
            # is now owned by AsyncGraphExecutor.  Progress the earliest
            # backend event before consuming a later rank completion, so an
            # unrelated P2D flow can change the service rate of an active EP
            # flow (and vice versa).
            backend_time = self.executor.next_event_time()
            if (backend_time is None and self.executor.has_pending()):
                # Wake events can remain in the control-plane heap after a
                # graph callback.  They must not mask a data-plane/DAG stall:
                # there is no legitimate next event when jobs remain but the
                # executor has neither local work nor an active/pending flow.
                raise RuntimeError(
                    "FlowSim executor stalled with pending DAGs: %s" %
                    self.executor.stall_report())
            if (backend_time is not None and
                    (not self.events or backend_time < self.events[0][0])):
                completions = self.executor.advance()
                for finish, ranks, _job_id in completions:
                    for rank in ranks:
                        self.sequence += 1
                        heapq.heappush(
                            self.events,
                            (finish, self.sequence, rank, False, None))
                continue
            if not self.events:
                if self.executor.has_pending():
                    # A same-timestamp local event may have been inserted by a
                    # graph callback.  If next_event_time() is None, however,
                    # there is no event to consume: continuing here would
                    # silently spin forever and hide an incomplete P2D/EP DAG.
                    if self.executor.next_event_time() is None:
                        raise RuntimeError(
                            "FlowSim executor stalled with pending DAGs: %s" %
                            self.executor.stall_report())
                    continue
                # The controller can need one final control-plane poll after
                # every rank replied ``pass``/``done`` and no data-plane flow
                # remains. HTSim uses the same idle wakeup mechanism. This
                # wakeup carries no compute or network completion; it merely
                # lets the frontend send ``exit`` or discover a future
                # request arrival. Raising here made a valid multi-request
                # run fail after all communication had already completed.
                sleeping_ranks = [
                    index for index, is_sleeping in enumerate(self.sleeping)
                    if is_sleeping]
                if not sleeping_ranks:
                    raise RuntimeError("FlowSim worker has no pending event")
                # Wake every sleeping rank once.  Waking only the first rank
                # can strand a TP peer in ``pass`` forever: the frontend only
                # observes instance completion after each physical rank has
                # reported the terminal control-plane state.
                for sleeping_rank in sleeping_ranks:
                    self._queue_wake(sleeping_rank, self.now + 1)
                continue
            finish, _, rank, wake, generation = heapq.heappop(self.events)
            if wake:
                self.wake_pending[rank] = False
                self.wake_urgent[rank] = False
                if generation != self.wake_generation[rank]:
                    continue
            # A real graph command can be installed while a wakeup generated
            # by the preceding graph is still in the heap.  That wakeup is a
            # scheduler poll, not a second completion of the new graph.  If
            # the rank already has a scheduled real graph, discard the stale
            # wake event; otherwise it can be reported at the same timestamp
            # and the serving frontend may incorrectly retire the new batch.
            if wake and self.scheduled[rank]:
                continue
            self.now = max(self.now, int(finish))
            self.scheduled[rank] = False
            # A real graph completion is a global progress point.  Reopen
            # ranks that were suppressed by an ordinary pass so the serving
            # scheduler can observe the new state once.  A deadline wakeup or
            # an explicit pass -1 is only a local scheduler poll; propagating
            # it to every sleeping rank recreates a pass storm.
            if not wake:
                # Ordinary graph completion only reopens ordinary sleeping
                # ranks.  A future ``pass <arrival>`` is invalidated by the
                # explicit ``pass -1`` state-change marker instead; doing the
                # broad wake on every graph completion creates a huge control
                # event stream on long decode traces.
                for other_rank, is_sleeping in enumerate(self.sleeping):
                    if is_sleeping and other_rank != rank:
                        self.sleeping[other_rank] = False
                        self._queue_wake(other_rank, self.now)
            self._emit(rank, wake=wake)
        print("Checking Non-Exited Systems ...", flush=True)
        print("All Request Has Been Exited", flush=True)
        self.executor.flush_link_telemetry()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workload-configuration", required=True)
    parser.add_argument("--total-ranks", type=int, required=True)
    parser.add_argument("--topology", required=True)
    parser.add_argument("--policy", default="FAIR")
    parser.add_argument("--telemetry", default=None)
    parser.add_argument("--mtu", type=int, default=4096)
    parser.add_argument(
        "--kv-backpressure", choices=["OFF", "FINITE_BUFFER"],
        default="OFF",
        help="optional sender-side P2D release buffer sensitivity")
    parser.add_argument(
        "--kv-buffer-bytes", type=int, default=0,
        help="per-prefill-rank/request P2D staging capacity; requires FINITE_BUFFER")
    parser.add_argument(
        "--critical-flow-file", default=None,
        help="offline oracle EP flow IDs, one per line")
    parser.add_argument(
        "--parallel-link-mode", choices=["AGGREGATE", "HASHED_PHYSICAL"],
        default="AGGREGATE",
        help="parallel-link resource model: aggregate fluid capacity (default) "
             "or deterministic one-flow-per-physical-link sensitivity mode")
    parser.add_argument("--decode-ranks", default=None,
                        help="comma-separated physical ranks whose EP is Decode-side")
    parser.add_argument("--rank-groups", default="",
                        help="semicolon-separated physical rank groups, e.g. 0;1,2;3,4")
    parser.add_argument(
        "--remote-kv-plan", default=None,
        help="optional JSON plan of model-derived remote-KV fetches by request")
    parser.add_argument(
        "--remote-kv-mode", choices=["LEGACY", "REMOTE_PREFIX_PD_BASELINE",
                                      "SPLIT_SOURCE_KV_ASSEMBLY"],
        default="LEGACY",
        help="remote-KV dependency semantics: legacy, R->P->D baseline, or V1 split-source")
    args = parser.parse_args()
    if args.remote_kv_plan:
        with open(args.remote_kv_plan, encoding="utf-8") as stream:
            payload = json.load(stream)
        args.remote_kv_plan = dict(payload.get("request_plans", payload))
        if "warmup" in payload:
            args.remote_kv_plan["__warmup__"] = payload["warmup"]
    else:
        args.remote_kv_plan = {}
    del args.workload_configuration, args.mtu
    if args.decode_ranks is not None:
        args.decode_ranks = [int(item) for item in args.decode_ranks.split(",")
                             if item]
    raw_rank_groups = args.rank_groups
    args.rank_groups = []
    for group in raw_rank_groups.split(";"):
        members = [int(item) for item in group.split(",") if item]
        if members:
            args.rank_groups.append(members)
    Worker(args).run()


if __name__ == "__main__":
    main()
