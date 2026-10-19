import logging
import math
from contextlib import nullcontext
from io import TextIOWrapper
from typing import Any, List
from enum import Enum

from ...schema.protobuf.et_def_pb2 import *
from ...schema.protobuf.et_def_pb2 import AttributeProto as ChakraAttr
from ..third_party.utils.protolib import encodeMessage as encode_message


def _append_attr(node: Any, attribute: Any) -> None:
    """Append a protobuf AttributeProto across protobuf runtime versions.

    Recent protobuf Python runtimes expose repeated message fields through
    ``extend``/``add`` but no longer provide the list-like ``append`` method.
    ``extend`` copies the message and works with both the generated Chakra
    bindings used by the simulator and older protobuf releases.
    """
    node.attr.extend([attribute])


def _push_marker_fields(layer_name: str):
    """Parse the compact NIXL Push marker envelope, if present."""
    parts = str(layer_name).split('|')
    if not parts or parts[0] not in ('nixl_push_write', 'nixl_push_settlement', 'nixl_push_commit'):
        return None
    fields = {'kind': parts[0].rsplit('_', 1)[-1]}
    for item in parts[1:]:
        if '=' not in item:
            continue
        key, value = item.split('=', 1)
        try:
            fields[key] = int(value)
        except ValueError:
            fields[key] = value
    if 'r' not in fields:
        raise ValueError('NIXL Push marker has no request id: %s' % layer_name)
    return fields


# Memory type is deprecated for latest version of chakra & astra-sim
# It only uses tensor_size for the remote memory issue in Workload.cc
# Added memory types using enum and add tensor_loc in node attribute in et_feeder_node.cpp
class MemoryType(Enum):
    INVALID_MEMORY = 0
    LOCAL_MEMORY = 1
    REMOTE_MEMORY = 2
    CXL_MEMORY = 3
    STORAGE_MEMORY = 4


class Layer:
    def __init__(self, line: str = None, cols: List[str] = None):
        try:
            # ``cols`` lets a caller that already holds the fields skip the
            # format-and-resplit round trip; ``line`` is the text path.
            col = cols if cols is not None else line.strip().split()
            if col[0] == 'EXPERT': # If Expert Flag
                self.name = col[0]
                self.expert_num = col[1]
                self.comm_type, self.involved_dim = self._parse_comm_type(str(col[2]) if len(col) > 2 else "NONE")
                self.comm_size = int(col[3]) if len(col) > 3 else 0
                self.a2a_route_id = (
                    int(col[4]) if self.comm_type == "A2A_P2P" and len(col) > 4
                    else None)
                self.is_expert = True
                self.is_pim = False
                self.comm_node = None
                self.comp_node = None
            elif col[0] == 'PIM': # If PIM Flag
                self.name = col[0]
                self.pim_num = col[1]
                self.is_expert = False
                self.is_pim = True
                self.comm_node = None
                self.comp_node = None
                self.comm_type = "NONE"
                self.involved_dim = None
            else:
                self.is_expert = False
                self.is_pim = False
                self.name = col[0]

                # compuation
                self.comp_time = int(col[1])
                self.comp_node = None

                # memory
                self.input_memory_loc = str(col[2])
                self.input_memory_size = int(col[3])
                self.input_memory_node = None
                self.weight_memory_loc = str(col[4])
                self.weight_memory_size = int(col[5])
                self.weight_memory_node = None
                self.output_memory_loc = str(col[6])
                self.output_memory_size = int(col[7])
                self.output_memory_node = None

                # communication (supports ALLREDUCE:1,0 format for involved_dim)
                self.comm_type, self.involved_dim = self._parse_comm_type(str(col[8]))
                self.comm_size = int(col[9])
                self.comm_node = None

                self.misc = str(col[10])
        except:
            raise ValueError(f"Cannot parse the following layer -- \"{line}\"")

    @staticmethod
    def _parse_comm_type(s: str):
        """Parse comm_type string, extracting optional involved_dim.

        'ALLREDUCE:1,0' -> ('ALLREDUCE', [True, False])
        'ALLTOALL'      -> ('ALLTOALL', None)
        'NONE'          -> ('NONE', None)
        """
        if ':' in s:
            comm_type, dim_str = s.split(':', 1)
            involved_dim = [v == '1' for v in dim_str.split(',')]
            return comm_type, involved_dim
        return s, None
        
class LLMConverter:
    def __init__(
        self,
        input_filename: str,
        output_filename: str,
        num_npus: int,
        npu_offset: int = 0,
        local_offloading: bool = False,
        pd_decode_offset: int = None,
        pd_decode_tp: int = None,
        pd_decode_pp: int = None,
        ep_global_ranks: List[int] = None,
        a2a_routing: List[dict] = None,
        event_metadata: dict = None,
    ):
        self.input_filename = input_filename
        self.output_filename = output_filename
        self.num_npus = num_npus
        self.npu_offset = npu_offset
        self.local_offloading = local_offloading
        # When set, P/D KV sends target the actual decode instance's global
        # rank range. ``pd_decode_tp`` lets a prefill TP shard fan out only to
        # the overlapping Decode TP shards. None preserves the legacy
        # shadow-rank behavior.
        self.pd_decode_offset = pd_decode_offset
        self.pd_decode_tp = pd_decode_tp
        self.pd_decode_pp = pd_decode_pp
        self.ep_global_ranks = tuple(int(rank) for rank in (ep_global_ranks or []))
        self.a2a_routing = {
            int(record["route_id"]): record for record in (a2a_routing or [])
        }
        # Serving provenance is optional and is consumed only by the
        # instrumentation path. It never changes graph dependencies or bytes.
        self.event_metadata = event_metadata or {}
        self.next_node_id = 0

        # For send & recv nodes
        self.next_comm_tag = 0
        self.comm_tag_dict = dict()

        # Set by convert_rows so get_layers can return them instead of
        # parsing a file. See convert_rows.
        self._layers = None

    def _pd_kv_destinations(self, npu_group: int, local_tp_rank: int,
                            source_tp: int, comm_size: int):
        """Return physical Decode-rank destinations for one prefill KV shard.

        A P/D handoff moves K/V shards, not a replicated full cache. Treat
        prefill and decode TP layouts as equal contiguous partitions of the KV
        dimension. Their intersections define the sender-to-receiver byte
        transfers, so the sum over all source ranks is conserved exactly and a
        Decode rank receives exactly its own shard.

        The legacy converter paired a source rank with one shadow rank. An
        explicit Decode offset without a Decode TP degree retains that old
        one-to-one mapping for backward compatibility. New serving runs pass
        ``pd_decode_tp`` and use the shard-aware path below.
        """
        if self.pd_decode_offset is None:
            return [(self.npu_offset + npu_group * source_tp + local_tp_rank +
                     self.num_npus, comm_size)]

        if self.pd_decode_tp is None:
            return [(self.pd_decode_offset + npu_group * source_tp +
                     local_tp_rank, comm_size)]

        decode_tp = int(self.pd_decode_tp)
        if source_tp < 1 or decode_tp < 1:
            raise ValueError(
                f"Invalid P/D TP layout: prefill_tp={source_tp}, "
                f"decode_tp={decode_tp}"
            )
        if self.pd_decode_pp is not None and npu_group >= int(self.pd_decode_pp):
            raise ValueError(
                f"Prefill pipeline stage {npu_group} has no matching Decode "
                f"stage in pp_size={self.pd_decode_pp}"
            )

        # Python 3.8 is still a supported simulator runtime, where
        # ``math.lcm`` is unavailable.
        common_units = source_tp * decode_tp // math.gcd(source_tp, decode_tp)
        source_units = common_units // source_tp
        source_start = local_tp_rank * source_units
        source_end = source_start + source_units
        if comm_size % source_units != 0:
            raise ValueError(
                f"P/D KV shard size {comm_size} is not divisible by the "
                f"source TP partition ({source_units} units); use a TP layout "
                "that partitions the model KV dimension exactly"
            )

        bytes_per_unit = comm_size // source_units
        decode_stage_offset = self.pd_decode_offset + npu_group * decode_tp
        destinations = []
        for decode_local_rank in range(decode_tp):
            decode_units = common_units // decode_tp
            decode_start = decode_local_rank * decode_units
            decode_end = decode_start + decode_units
            overlap_units = max(0, min(source_end, decode_end) -
                                max(source_start, decode_start))
            if overlap_units:
                destinations.append((decode_stage_offset + decode_local_rank,
                                     overlap_units * bytes_per_unit))
        if not destinations or sum(size for _, size in destinations) != comm_size:
            raise RuntimeError(
                "P/D KV shard mapper failed to conserve bytes for "
                f"prefill_tp={source_tp}, decode_tp={decode_tp}, "
                f"source_rank={local_tp_rank}, bytes={comm_size}"
            )
        return destinations

    def _emit_pd_kv_sends(self, sender_stream, receiver_stream, parent_node,
                           npu_group: int, local_tp_rank: int,
                           source_tp: int, npu_id: int, comm_size: int,
                           layer_id: int, layer_name: str = 'kv_proj') -> list:
        """Emit one model-derived P2D K/V shard to actual Decode ranks.

        ``receiver_stream`` is used only by the legacy shadow-rank path.  In
        explicit P/D mode, the physical SEND targets an actual Decode rank;
        the Decode serving scheduler is notified by the frontend once every
        real Prefill sender graph has completed.
        """
        if parent_node is None:
            raise ValueError("P2D KV SEND has no completed prefill dependency")
        destinations = self._pd_kv_destinations(
            npu_group, local_tp_rank, source_tp, comm_size)
        send_nodes = []
        for pd_dst, pd_bytes in destinations:
            send_kv_node = self.get_comm_node(
                is_send=True,
                layer_name=layer_name,
                comm_type="NONE",
                comm_size=pd_bytes,
                comm_src=npu_id,
                comm_dst=pd_dst,
                id=layer_id,
            )
            self.add_parent(send_kv_node, parent_node)
            encode_message(sender_stream, send_kv_node)
            send_nodes.append(send_kv_node)

            if isinstance(receiver_stream, dict):
                # Explicit P/D mode writes all physical Decode receive nodes
                # through the same converter instance as the corresponding
                # sender nodes.  This is important because comm_tag_dict is
                # rank-independent within one conversion: a separate
                # receiver conversion would silently allocate different tags.
                receiver = receiver_stream.get(pd_dst)
                if receiver is None:
                    raise RuntimeError(
                        f"No receiver stream for physical Decode rank {pd_dst}")
                recv_kv_node = self.get_comm_node(
                    is_send=False,
                    layer_name=layer_name,
                    comm_type="NONE",
                    comm_size=pd_bytes,
                    comm_src=npu_id,
                    comm_dst=pd_dst,
                    id=layer_id,
                )
                encode_message(receiver, recv_kv_node)
            elif self.pd_decode_offset is None:
                recv_kv_node = self.get_comm_node(
                    is_send=False,
                    layer_name=layer_name,
                    comm_type="NONE",
                    comm_size=pd_bytes,
                    comm_src=npu_id,
                    comm_dst=pd_dst,
                    id=layer_id,
                )
                encode_message(receiver_stream, recv_kv_node)
        return send_nodes

    def get_global_metadata(self):
        # ``input_file`` carries the trace's *path*, not its contents.
        #
        # It used to embed the whole trace text. Nothing consumes it:
        # ETFeeder::readGlobalMetadata() reads the message into a local
        # shared_ptr and drops it on the floor, and no other reader touches
        # the attribute. So every byte of it was written by the converter,
        # re-parsed by the feeder's protobuf reader, and discarded.
        #
        # It was not a small overhead. On the swe-bench MoE DP+EP example a
        # trace is ~82 KB of a 117 KB .et -- 70% of the file -- and the
        # simulator generates 8,810 of them for one session, so it was
        # ~720 MB of encode/write/read/parse per run, plus a second full
        # read of the trace file here purely to obtain the text.
        #
        # The path keeps the provenance that made this attribute useful for
        # debugging; the trace itself is written to disk by --save-trace-text.
        attr = [
            ChakraAttr(name="schema", string_val="1.0.2-chakra.0.0.4"),
            ChakraAttr(name="input_file", string_val=self.input_filename),
        ]
        metadata = GlobalMetadata(attr=attr)
        return metadata
    
    def get_layers(self, f: TextIOWrapper) -> List[Layer]:
        if self._layers is not None:
            return self._layers
        layers: List[Layer] = []
        for line in f:
            layers.append(Layer(line))
        return layers

    @staticmethod
    def _replicated_single_expert(layers: List[Layer], start: int) -> bool:
        """Identify EP1 compute replicated across TP ranks.

        The frontend emits one EXPERT 0 marker with no dispatch for EP1.
        Multi-rank EP emits several markers or a dispatch collective, so
        its experts remain assigned to individual ranks below.
        """
        marker = layers[start]
        if (marker.expert_num != '0' or marker.comm_type != 'NONE' or
                marker.comm_size != 0):
            return False
        end = start + 1
        while end < len(layers) and not layers[end].is_expert:
            end += 1
        return (end < len(layers) and layers[end].expert_num == 'END' and
                layers[end].comm_type == 'NONE' and
                layers[end].comm_size == 0)

    def convert_rows(self, header_line: str, rows: List[List[str]]) -> None:
        """Convert from pre-parsed field lists, with no text round trip.

        The simulator already holds every field. Formatting them into padded
        columns, writing the file, reading it back and splitting each line
        again is pure overhead now that the converter runs in the same
        process -- 0.65 ms of formatting and writing per batch plus 0.9 ms of
        reading and re-parsing, against 8,810 batches on the swe-bench MoE
        DP+EP example.

        Nothing downstream changes: convert_common, convert_prefill and
        convert_event each touch the file handle exactly once, to call
        get_layers, so seeding the layers is the whole of it. Header parsing
        mirrors convert() on a string instead of a readline, and num_layers
        is len(rows) -- which is precisely what convert() reads off line two,
        since that is what the writer puts there.
        """
        self._layers = [Layer(cols=cols) for cols in rows]

        first_line = header_line.strip().split()
        execution_type = first_line[0]

        header = {}
        fields = first_line[1:]
        for i in range(0, len(fields) - 1, 2):
            if fields[i].endswith(":"):
                header[fields[i][:-1]] = fields[i + 1]

        num_npu_group = int(header.get("model_parallel_NPU_group", 0))
        boundary_str = header.get("pp_stage_boundaries", "")
        stage_boundaries = (
            [int(b) for b in boundary_str.split(",")] if boundary_str else []
        )
        num_layers = len(rows)

        if execution_type in ("COLOCATED", "DECODE"):
            if num_npu_group <= 0:
                raise ValueError(f"model_parallel_NPU_group <= 0")
            self.convert_common(None, num_layers, num_npu_group, stage_boundaries)
        elif execution_type == "PREFILL":
            if num_npu_group <= 0:
                raise ValueError(f"model_parallel_NPU_group <= 0")
            self.convert_prefill(None, num_layers, num_npu_group, stage_boundaries)
        elif execution_type == "EVENT":
            self.convert_event(None, num_layers)
        else:
            raise ValueError(f"Unsupported execution type, {execution_type}")

    def get_next_node_id(self) -> int:
        ret = self.next_node_id
        self.next_node_id += 1
        return ret
    
    def get_next_comm_tag(self) -> int:
        ret = self.next_comm_tag
        self.next_comm_tag += 1
        return ret

    def get_node(self, name: str, node_type: NodeType) -> Any:
        node = Node()
        node.id = self.get_next_node_id()
        node.name = name
        node.type = node_type
        return node

    def get_comp_node(self, layer_name: str, comp_time: int) -> Any:
        node = self.get_node("COMP_NODE_" + layer_name, COMP_NODE)
        node.duration_micros = comp_time
        return node
    
    def get_comm_type(self, comm_type: str) -> int:
        if comm_type == "ALLREDUCE":
            return ALL_REDUCE
        elif comm_type in ("ALLTOALL", "A2A_P2P"):
            return ALL_TO_ALL
        elif comm_type == "ALLGATHER":
            return ALL_GATHER
        elif comm_type == "REDUCESCATTER":
            return REDUCE_SCATTER
        return 0
    
    def get_comm_coll_node(self, layer_name: str, comm_type: str, comm_size: int,
                           involved_dim: list = None, layer_id: int = 0) -> Any:
        node = self.get_node(f"COMM_COLL_NODE_{layer_name}_{comm_type}", COMM_COLL_NODE)
        _append_attr(node, ChakraAttr(name="comm_type", int64_val=self.get_comm_type(comm_type)))
        _append_attr(node, ChakraAttr(name="comm_size", int64_val=comm_size))
        self._add_event_metadata(node, layer_name, layer_id)
        if involved_dim is not None:
            _append_attr(node, ChakraAttr(name="involved_dim",
                                          bool_list=BoolList(values=involved_dim)))
        return node

    def get_comm_node(self, is_send: bool, layer_name: str, comm_type: str, comm_size: int,
                           comm_src: int, comm_dst: int, id: int = 0,
                           explicit_tag: int = None) -> Any:
        if is_send:
            node = self.get_node(
                    f"COMM_SEND_NODE_{layer_name}_{comm_type}_{comm_src}_{comm_dst}",
                    COMM_SEND_NODE)
        else:
            node = self.get_node(
                    f"COMM_RECV_NODE_{layer_name}_{comm_type}_{comm_src}_{comm_dst}",
                    COMM_RECV_NODE)
        _append_attr(node, ChakraAttr(name="comm_type", int64_val=self.get_comm_type(comm_type)))
        _append_attr(node, ChakraAttr(name="comm_src", int32_val=comm_src))
        _append_attr(node, ChakraAttr(name="comm_dst", int32_val=comm_dst))
        _append_attr(node, ChakraAttr(name="comm_size", int64_val=comm_size))
        comm_key = f"{comm_src}_{comm_dst}_{id}"
        if explicit_tag is not None:
            _append_attr(node, ChakraAttr(name="comm_tag", int32_val=explicit_tag))
        elif comm_key in self.comm_tag_dict:
            _append_attr(node, ChakraAttr(name="comm_tag", int32_val=self.comm_tag_dict[comm_key]))
        else:
            new_tag = self.get_next_comm_tag()
            _append_attr(node, ChakraAttr(name="comm_tag", int32_val=new_tag))
            self.comm_tag_dict[comm_key] = new_tag

        self._add_event_metadata(node, layer_name, id)

        # check if SEND/RECV pair have same tags
        # print(f"name: {node.name}, src: {node.comm_src}, dst: {node.comm_dst}, size: {node.comm_size}, key: {comm_key}, tag: {node.comm_tag}")
        return node

    def _add_event_metadata(self, node: Any, layer_name: str,
                            layer_id: int = 0) -> None:
        """Attach serving provenance without affecting ASTRA execution."""
        meta = self.event_metadata
        if not meta:
            return
        request_ids = meta.get("request_ids", [])
        push = _push_marker_fields(layer_name)
        if push is not None:
            request_ids = [int(push["r"])]
            event_type = ({'write': 4, 'settlement': 6, 'commit': 5}[push['kind']])
        elif layer_name == "kv_proj":
            request_ids = meta.get("pd_request_ids", request_ids)
            event_type = 1
        elif layer_name == "expert_start":
            request_ids = (meta.get("decode_request_ids", []) or
                           meta.get("pd_request_ids", request_ids))
            event_type = 2
        elif layer_name == "expert_end":
            request_ids = (meta.get("decode_request_ids", []) or
                           meta.get("pd_request_ids", request_ids))
            event_type = 3
        else:
            event_type = 0
        request_ids = [str(value) for value in request_ids]
        _append_attr(node, ChakraAttr(
            name="request_ids", string_val=";".join(request_ids)))
        if len(request_ids) == 1:
            _append_attr(node, ChakraAttr(
                name="request_id", uint64_val=int(request_ids[0])))
        _append_attr(node, ChakraAttr(
            name="batch_id", uint64_val=int(meta.get("batch_id", 0))))
        # Node ids are allocated independently for each rank's graph.  Use a
        # rank-independent identity for communication generated from the same
        # serving batch/layer instead; exact collective joins must not be
        # reconstructed from timestamps later.
        batch_id = int(meta.get("batch_id", 0))
        collective_batch_id = int(meta.get("ep_collective_batch_id", batch_id))
        collective_key = (collective_batch_id * 10000000 +
                          int(layer_id) * 10 + event_type)
        _append_attr(node, ChakraAttr(
            name="collective_batch_id",
            uint64_val=collective_batch_id))
        _append_attr(node, ChakraAttr(
            name="collective_id", uint64_val=collective_key))
        _append_attr(node, ChakraAttr(
            name="layer_id", uint64_val=int(layer_id)))
        _append_attr(node, ChakraAttr(
            name="event_type", uint64_val=event_type))
        _append_attr(node, ChakraAttr(
            name="serving_role",
            string_val=str(meta.get("execution_type", ""))))
        if push is not None:
            for key in ("s", "e", "f", "ep", "settled"):
                if key in push:
                    _append_attr(node, ChakraAttr(
                        name={"s": "push_start_tokens",
                              "e": "push_end_tokens",
                              "f": "push_final",
                              "ep": "push_epoch",
                              "settled": "push_settled_tokens"}[key],
                        uint64_val=int(push[key])))
    
    def get_mem_type(self, mem_type: str) -> int:
        mem_type = mem_type.split(':')[0]  # Exclude the device number if present
        if mem_type == "LOCAL":
            return MemoryType.LOCAL_MEMORY.value
        elif mem_type == "REMOTE":
            return MemoryType.REMOTE_MEMORY.value
        elif mem_type == "CXL":
            return MemoryType.CXL_MEMORY.value
        elif mem_type == "STORAGE":
            return MemoryType.STORAGE_MEMORY.value
        return MemoryType.INVALID_MEMORY.value
    
    def get_mem_device(self, mem_type: str) -> int:
        """
        Extract the device index from mem_type.

        Supported formats:
        - "REMOTE"          -> returns 0
        - "REMOTE:1"        -> returns 1
        - "REMOTE:1.3"      -> returns 1  (device = 1, channel = 3)
        """
        parts = mem_type.split(":", 1)
        if len(parts) == 2:
            # parts[1] may be "1" or "1.3"
            dev_part = parts[1].split(".", 1)[0]
            if dev_part.isdigit():
                return int(dev_part)
        return 0  # Default device number


    def get_mem_channel(self, mem_type: str) -> int:
        """
        Extract the channel index from mem_type.

        Supported formats:
        - "REMOTE"          -> returns 0
        - "REMOTE:1"        -> returns 0  (no channel specified)
        - "REMOTE:1.3"      -> returns 3  (channel = 3)
        """
        parts = mem_type.split(":", 1)
        if len(parts) == 2:
            # parts[1] may be "1" or "1.3"
            sub = parts[1].split(".", 1)
            if len(sub) == 2:
                chan_part = sub[1]
                if chan_part.isdigit():
                    return int(chan_part)
        return 0  # Default channel number


    def get_memory_load_node(self, layer_name: str, tensor_type: str, mem_type: str, tensor_size: int) -> Any:
        node = self.get_node("MEM_LOAD_NODE_" + layer_name + "_" + tensor_type, MEM_LOAD_NODE)
        _append_attr(node, ChakraAttr(name="tensor_size", uint64_val=tensor_size))
        _append_attr(node, ChakraAttr(name="tensor_loc", uint32_val=self.get_mem_type(mem_type)))
        _append_attr(node, ChakraAttr(name="tensor_device", uint32_val=self.get_mem_device(mem_type)))
        return node

    def get_memory_store_node(self, layer_name: str, tensor_type: str, mem_type: str, tensor_size: int) -> Any:
        node = self.get_node("MEM_STORE_NODE_" + layer_name + "_" + tensor_type, MEM_STORE_NODE)
        _append_attr(node, ChakraAttr(name="tensor_size", uint64_val=tensor_size))
        _append_attr(node, ChakraAttr(name="tensor_loc", uint32_val=self.get_mem_type(mem_type)))
        _append_attr(node, ChakraAttr(name="tensor_device", uint32_val=self.get_mem_device(mem_type)))
        return node

    def get_pim_compute_node(self, layer_name: str, tensor_type: str, comp_time: int, mem_type: str, tensor_size: int) -> Any:
        node = self.get_node("PIM_COMP_NODE_" + layer_name + "_" + tensor_type, PIM_COMP_NODE)
        node.duration_micros = comp_time
        _append_attr(node, ChakraAttr(name="tensor_size", uint64_val=tensor_size))
        _append_attr(node, ChakraAttr(name="tensor_loc", uint32_val=self.get_mem_type(mem_type)))
        _append_attr(node, ChakraAttr(name="tensor_device", uint32_val=self.get_mem_device(mem_type)))
        _append_attr(node, ChakraAttr(name="tensor_channel", uint32_val=self.get_mem_channel(mem_type)))
        return node
        
    def add_parent(self, child_node: Any, parent_node: Any) -> None:
        child_node.data_deps.append(parent_node.id)

    def _exact_a2a_record(self, layer: Layer) -> dict:
        """Resolve and validate one model-derived variable A2A route matrix."""
        if layer.a2a_route_id is None:
            raise ValueError("A2A_P2P EXPERT marker has no route id")
        record = self.a2a_routing.get(layer.a2a_route_id)
        if record is None:
            raise ValueError(
                f"A2A_P2P route id {layer.a2a_route_id} is absent from trace metadata")
        if record.get("realization") != "EXACT_P2P_ROUTED_ALLTOALL":
            raise ValueError(
                f"A2A_P2P route id {layer.a2a_route_id} has realization "
                f"{record.get('realization')!r}, not exact P2P")
        ep_size = int(record.get("ep_size", 0))
        matrix = record.get("pair_matrix")
        if (ep_size < 1 or len(self.ep_global_ranks) != ep_size or
                not isinstance(matrix, list) or len(matrix) != ep_size or
                any(not isinstance(row, list) or len(row) != ep_size
                    for row in matrix)):
            raise ValueError(
                "A2A_P2P requires one explicit physical rank per EP rank; "
                "use a PP=1 topology whose ep_global_ranks length equals ep_size")
        if len(set(self.ep_global_ranks)) != ep_size:
            raise ValueError("A2A_P2P ep_global_ranks contains duplicates")
        if ep_size > 256:
            raise ValueError("A2A_P2P supports at most 256 EP ranks per trace")
        return record

    @staticmethod
    def _exact_a2a_tag(layer_id: int, phase: str, src_rank: int,
                       dst_rank: int) -> int:
        """Return a converter-independent tag for one peer message.

        DP members convert their local rank graphs independently.  The normal
        converter tag allocator is instance-local, so exact peer flows use an
        explicit tag derived from immutable trace coordinates instead.
        """
        if layer_id < 0 or layer_id >= 16384:
            raise ValueError("A2A_P2P trace layer id exceeds tag encoding range")
        phase_bit = 0 if phase == "expert_start" else 1
        return ((layer_id * 2 + phase_bit) << 16) | (src_rank << 8) | dst_rank

    def emit_exact_a2a_p2p(self, graph, layer: Layer, phase: str,
                            base_node: Any, npu_id: int, layer_id: int) -> Any:
        """Emit an exact variable-byte A2A phase as native SEND/RECV nodes.

        The emitted join waits for every non-local send and receive.  It
        therefore retains a collective-call completion boundary for the
        compute graph while the native ns-3 backend sees the real individual
        source-to-owner messages rather than a padded uniform collective.
        """
        record = self._exact_a2a_record(layer)
        ep_size = int(record["ep_size"])
        try:
            local_rank = self.ep_global_ranks.index(npu_id)
        except ValueError as error:
            raise ValueError(
                f"A2A_P2P rank {npu_id} is not in ep_global_ranks "
                f"{list(self.ep_global_ranks)}") from error
        matrix = record["pair_matrix"]
        bytes_per_pair = int(record.get("bytes_per_expert_token", 0))
        if bytes_per_pair <= 0:
            raise ValueError("A2A_P2P route record has no positive token byte size")

        if phase == "expert_start":
            outgoing = matrix[local_rank]
            incoming = [matrix[peer][local_rank] for peer in range(ep_size)]
        elif phase == "expert_end":
            outgoing = [matrix[peer][local_rank] for peer in range(ep_size)]
            incoming = matrix[local_rank]
        else:
            raise ValueError(f"Unexpected A2A_P2P phase {phase!r}")

        operations = []
        for peer_rank, pair_count in enumerate(outgoing):
            pair_count = int(pair_count)
            if peer_rank == local_rank or pair_count <= 0:
                continue
            node = self.get_comm_node(
                is_send=True, layer_name=phase, comm_type="ALLTOALL",
                comm_size=pair_count * bytes_per_pair, comm_src=npu_id,
                comm_dst=self.ep_global_ranks[peer_rank], id=layer_id,
                explicit_tag=self._exact_a2a_tag(
                    layer_id, phase, local_rank, peer_rank))
            self.add_parent(node, base_node)
            encode_message(graph, node)
            operations.append(node)

        for peer_rank, pair_count in enumerate(incoming):
            pair_count = int(pair_count)
            if peer_rank == local_rank or pair_count <= 0:
                continue
            node = self.get_comm_node(
                is_send=False, layer_name=phase, comm_type="ALLTOALL",
                comm_size=pair_count * bytes_per_pair,
                comm_src=self.ep_global_ranks[peer_rank], comm_dst=npu_id,
                id=layer_id,
                explicit_tag=self._exact_a2a_tag(
                    layer_id, phase, peer_rank, local_rank))
            self.add_parent(node, base_node)
            encode_message(graph, node)
            operations.append(node)

        join = self.get_comp_node(f"{phase}_a2a_p2p_join_{layer_id}", 0)
        if operations:
            for node in operations:
                self.add_parent(join, node)
        else:
            self.add_parent(join, base_node)
        encode_message(graph, join)
        return join

    def emit_expert_communication(self, graph, layer: Layer, phase: str,
                                  base_node: Any, npu_id: int,
                                  layer_id: int) -> Any:
        """Emit either a native collective or the exact routed A2A extension."""
        if layer.comm_type == "A2A_P2P":
            return self.emit_exact_a2a_p2p(
                graph, layer, phase, base_node, npu_id, layer_id)
        node = self.get_comm_coll_node(
            phase, layer.comm_type, layer.comm_size, layer.involved_dim,
            layer_id)
        self.add_parent(node, base_node)
        encode_message(graph, node)
        return node

    def get_stage_edges(self, num_layers: int, num_npu_group: int,
                        stage_boundaries: List[int]) -> List[Any]:
        """Resolve the [start, end) trace-line range owned by each pipeline stage.

        ``stage_boundaries`` comes from the trace header and holds the line
        index at which every stage after the first begins. The frontend puts
        those cuts on transformer-block boundaries, which is what makes the
        tensor crossing a stage boundary the hidden state: the sending
        layer's output_size then equals the receiving layer's input_size, and
        the SEND/RECV pair matches in ASTRA-sim (its callback tracker keys on
        chunk size, so a mismatch deadlocks the run instead of erroring).
        Splitting the line count evenly instead lands cuts inside a block --
        e.g. between qkv_proj and rotary_emb, whose declared sizes differ by
        the V projection -- so do not reintroduce that.
        """
        if num_npu_group == 1:
            return [(0, num_layers)]
        if len(stage_boundaries) != num_npu_group - 1:
            raise ValueError(
                f"trace declares model_parallel_NPU_group: {num_npu_group} but "
                f"carries {len(stage_boundaries)} pp_stage_boundaries "
                f"(expected {num_npu_group - 1}); regenerate the trace")
        edges = [0] + list(stage_boundaries) + [num_layers]
        for i in range(len(edges) - 1):
            if not 0 <= edges[i] < edges[i + 1] <= num_layers:
                raise ValueError(
                    f"pp_stage_boundaries {stage_boundaries} are not a strictly "
                    f"increasing split of {num_layers} layers")
        return [(edges[i], edges[i + 1]) for i in range(num_npu_group)]

    def convert_common(self, f: TextIOWrapper, num_layers: int, num_npu_group: int,
                       stage_boundaries: List[int] = None):
        layers: list[Layer] = self.get_layers(f)

        # vllm: check eviction or load
        evict = None
        load = None
        ev_ld_cnt = 0
        for i in range(2):
            if 'kv_load' in layers[i].name:
                load = self.get_memory_load_node(
                            layers[i].name,
                            "WEIGHT",
                            layers[i].weight_memory_loc,
                            layers[i].weight_memory_size, # already per npu kv_cache size
                        )
            elif 'kv_evict' in layers[i].name:
                evict = self.get_memory_store_node(
                            layers[i].name,
                            "WEIGHT",
                            layers[i].weight_memory_loc,
                            layers[i].weight_memory_size,
                        )
            else:
                continue
            ev_ld_cnt += 1
            
        layers = layers[ev_ld_cnt:]
        num_layers -= ev_ld_cnt

        if self.num_npus % num_npu_group != 0: print("Warning! num_npus % num_npu_group != 0, Some npus won't do anything!")
        npus_per_group = self.num_npus // num_npu_group
        if npus_per_group == 1: # same as pipeline parallelism, ignore all reduce
            use_comm = False
        else:
            use_comm = True
        stage_edges = self.get_stage_edges(num_layers, num_npu_group,
                                           stage_boundaries or [])

        for npu_group in range(num_npu_group):
            for npu_offset in range(npus_per_group):
                # Re-read the authoritative edges per rank: the walk below may
                # rebind layer_end if it ever overruns.
                layer_start, layer_end = stage_edges[npu_group]
                npu_id = npu_group * npus_per_group + npu_offset + self.npu_offset
                output_filename = "%s.%d.et" % (self.output_filename, npu_id)
                first_comp_node = True
                with open(output_filename, "wb") as g:
                    global_metadata = self.get_global_metadata()
                    encode_message(g, global_metadata)
                    if evict != None:
                        encode_message(g, evict)
                    if load != None:
                        encode_message(g, load)
                    if npu_group == 0:
                        # Load Input
                        input_load_node = self.get_memory_load_node(
                            layers[layer_start].name,
                            "INPUT",
                            layers[layer_start].input_memory_loc,
                            layers[layer_start].input_memory_size,
                        )
                        encode_message(g, input_load_node)                  
                    else:
                        if layers[layer_start].is_expert or layers[layer_start].is_pim:
                            # Receive input (from the previous layer in another npu group)
                            receive_input_node = self.get_comm_node(
                                is_send=False,
                                layer_name=layers[layer_start-1].name,
                                comm_type=layers[layer_start-1].comm_type,
                                comm_size=layers[layer_start-1].output_memory_size,
                                comm_src=npu_id - npus_per_group,
                                comm_dst=npu_id
                            )
                            encode_message(g, receive_input_node)
                        else:
                            # Receive input (from the previous layer in another npu group)
                            receive_input_node = self.get_comm_node(
                                is_send=False,
                                layer_name=layers[layer_start].name,
                                comm_type=layers[layer_start].comm_type,
                                comm_size=layers[layer_start].input_memory_size,
                                comm_src=npu_id - npus_per_group,
                                comm_dst=npu_id
                            )
                            encode_message(g, receive_input_node)

                    expert_start = False
                    replicated_expert = False
                    pim_start = False
                    attn_remain = False # to handle remaining prefill attention after pim
                    pim_parent_nodes = []
                    pim_comp_nodes = []
                    past_pim_comp_nodes = []
                    last_batch_type = "BATCH_1"
                    layer_num = layer_start
                    while expert_start or pim_start or attn_remain or layer_num < layer_end:
                        if not layers[layer_num].is_expert and not layers[layer_num].is_pim: 
                            if (self.local_offloading or layers[layer_num].weight_memory_loc != "LOCAL") and layers[layer_num].weight_memory_size > 0:
                                # Load weight (for weight offloading)
                                weight_load_node = self.get_memory_load_node(
                                    layers[layer_num].name,
                                    "WEIGHT",
                                    layers[layer_num].weight_memory_loc,
                                    layers[layer_num].weight_memory_size,
                                )
                                layers[layer_num].weight_memory_node = weight_load_node
                                if expert_start:
                                    self.add_parent(weight_load_node, comp_node) # dependent to previous comp_node due to gate function
                                encode_message(g, weight_load_node)
                            # Compute
                            if layers[layer_num].comp_time != 0 and not pim_start: # pim computation is handled pim_comp_node
                                comp_node = self.get_comp_node(
                                    layers[layer_num].name, 
                                    layers[layer_num].comp_time)
                                layers[layer_num].comp_node = comp_node

                                # handle pim parent nodes, and if prefill attention remains wait until all attention is done (before o_proj)
                                if len(pim_parent_nodes) != 0:
                                    if attn_remain:
                                        for parent in pim_parent_nodes: 
                                            self.add_parent(comp_node, parent)
                                    pim_parent_nodes = [] # reset pim parent nodes

                                    if "attn" in layers[layer_num].name:
                                        attn_remain = False
                                else: 
                                    if first_comp_node:
                                        if npu_group == 0:
                                            self.add_parent(comp_node, input_load_node)
                                        else:
                                            self.add_parent(comp_node, receive_input_node)
                                        if evict != None:
                                            self.add_parent(comp_node, evict)
                                        if load != None:
                                            self.add_parent(comp_node, load)
                                        if layers[layer_num].weight_memory_node != None:
                                            self.add_parent(comp_node, layers[layer_num].weight_memory_node)
                                        first_comp_node = False
                                    else:
                                        if layers[layer_num].weight_memory_node != None:
                                            self.add_parent(comp_node, layers[layer_num].weight_memory_node)
                                        if layers[layer_num - 1].comm_node != None:
                                            self.add_parent(comp_node, layers[layer_num - 1].comm_node)
                                        elif layers[layer_num - 1].comp_node != None:
                                            self.add_parent(comp_node, layers[layer_num - 1].comp_node)
                                        else:
                                            self.add_parent(comp_node, layers[layer_num - 2].comp_node)

                                # handle pim_compute_mode dependency & should not be remaining attention
                                if not attn_remain and len(pim_comp_nodes) != 0:
                                    if layers[layer_num].misc == "NONE": # no sub-batch interleaving
                                        for pim_comp in pim_comp_nodes:
                                            self.add_parent(comp_node, pim_comp)
                                        pim_comp_nodes = [] # reset pim comp nodes
                                    elif layers[layer_num].misc != last_batch_type:
                                        if len(past_pim_comp_nodes) != 0:
                                            for pim_comp in past_pim_comp_nodes:
                                                self.add_parent(comp_node, pim_comp)
                                        past_pim_comp_nodes = pim_comp_nodes # update past pim comp nodes
                                        pim_comp_nodes = [] # reset pim comp nodes
                                        last_batch_type = layers[layer_num].misc

                                encode_message(g, comp_node)

                            # PIM compute
                            if pim_start:
                                pim_comp_node = self.get_pim_compute_node(
                                    layers[layer_num].name,
                                    "PIM",
                                    layers[layer_num].comp_time,
                                    layers[layer_num].input_memory_loc,
                                    layers[layer_num].input_memory_size + layers[layer_num].output_memory_size # load/store from pim
                                )
                                pim_comp_nodes.append(pim_comp_node)
                                for parent in pim_parent_nodes:
                                    self.add_parent(pim_comp_node, parent)
                                encode_message(g, pim_comp_node)

                            # Communication (if required)
                            if layers[layer_num].comm_type != "NONE" and use_comm:
                                comm_coll_node = self.get_comm_coll_node(layers[layer_num].name, layers[layer_num].comm_type, layers[layer_num].comm_size, layers[layer_num].involved_dim, layer_num)
                                # for j in range(self.num_dims):
                                # comm_coll_node.involved_dim.append(True)
                                layers[layer_num].comm_node = comm_coll_node
                                if layers[layer_num].comp_time != 0:
                                    self.add_parent(comm_coll_node, comp_node)
                                encode_message(g, comm_coll_node)
                            # add layer_num
                            layer_num += 1
                        # expert layer starts
                        elif layers[layer_num].is_expert:
                            # communication can happen even with one NPU in the group, for example, expert input gathering in data parallel
                            if not expert_start:
                                replicated_expert = self._replicated_single_expert(layers, layer_num)
                            if expert_start == False and layers[layer_num].comm_size > 0 and layers[layer_num].comm_type != "NONE": 
                                # Start of expert communication before expert computation.
                                comm_coll_node = self.emit_expert_communication(
                                    g, layers[layer_num], "expert_start", comp_node,
                                    npu_id, layer_num)
                                layers[layer_num].comm_node = comm_coll_node
                            expert_start = True
                            # check expert end
                            if layers[layer_num].expert_num == 'END':
                                expert_start = False
                                layers[layer_num].comp_node = comp_node # is latest comp_node
                                # End of expert communication after expert computation.
                                if layers[layer_num].comm_size > 0 and layers[layer_num].comm_type != "NONE":
                                    comm_coll_node = self.emit_expert_communication(
                                        g, layers[layer_num], "expert_end", comp_node,
                                        npu_id, layer_num)
                                    layers[layer_num].comm_node = comm_coll_node
                                layer_num += 1
                                continue
                            # round robin assignment
                            expert_id = int(layers[layer_num].expert_num) % npus_per_group
                            if not replicated_expert and npu_offset != expert_id:
                                # go to next expert
                                while True:
                                    layer_num += 1
                                    if layers[layer_num].is_expert:
                                        break
                            else:
                                layers[layer_num].comp_node = comp_node # is latest comp_node
                                layer_num += 1
                        # pim layer starts
                        elif layers[layer_num].is_pim:
                            pim_start = True
                            # check attention end
                            if layers[layer_num].pim_num == 'END':
                                pim_start = False
                                if "attn" in layers[layer_num + 1].name:
                                    attn_remain = True # prefill attn remains
                                layer_num += 1
                                continue
                            # add pim parent nodes for dependency
                            elif int(layers[layer_num].pim_num) == 0:
                                if first_comp_node:
                                    if npu_group == 0:
                                        pim_parent_nodes.append(input_load_node)
                                    else:
                                        pim_parent_nodes.append(receive_input_node)
                                    if evict != None:
                                        pim_parent_nodes.append(evict)
                                    if load != None:
                                        pim_parent_nodes.append(load)
                                    # discarded weight parent because attention has no weight
                                    first_comp_node = False
                                else:
                                    # discarded weight parent because attention has no weight
                                    if layers[layer_num - 1].comm_node != None:
                                        pim_parent_nodes.append(layers[layer_num - 1].comm_node)
                                    elif layers[layer_num - 1].comp_node != None:
                                        pim_parent_nodes.append(layers[layer_num - 1].comp_node)
                                    else:
                                        pim_parent_nodes.append(layers[layer_num - 1].comp_node)
                            # round robin assignment
                            pim_id = int(layers[layer_num].pim_num) % npus_per_group
                            if npu_offset != pim_id:
                                # go to next attention
                                while True:
                                    layer_num += 1
                                    if layers[layer_num].is_pim:
                                        break
                            else:
                                layer_num += 1

                    # The frontend cuts stages on transformer-block boundaries,
                    # so the walk above lands exactly on the stage edge. Expert
                    # and PIM blocks live inside a block and can no longer be
                    # straddled; warn loudly if that ever stops holding.
                    if layer_num != layer_end:
                        print(f"Warning! pipeline stage {npu_group} walked to "
                              f"layer {layer_num}, expected {layer_end}")
                        layer_end = layer_num

                    if npu_group == (num_npu_group - 1):
                        # Store output (for the last layer)
                        # The last layer is the sampler: what crosses back to
                        # the host is its OUTPUT, the sampled token ids, 4 bytes
                        # per sequence.
                        #
                        # Do not switch this back to input_memory_size. That read
                        # was a deliberate down-scaling when lm_head was the last
                        # trace layer: its output is the logits
                        # (num_seqs * vocab_size * dtype) and billing those to CPU
                        # memory every iteration was a large overcharge, so the
                        # smaller input (the hidden state) stood in. Once sampler
                        # was appended as the new last layer the two swapped
                        # roles -- sampler's output is the token ids and its input
                        # is the logits -- so reading the input landed back on
                        # exactly the tensor the workaround existed to avoid.
                        output_store_node = self.get_memory_store_node(
                            layers[layer_end - 1].name,
                            "OUTPUT",
                            layers[layer_end - 1].output_memory_loc,
                            layers[layer_end - 1].output_memory_size,
                        )
                        # if pim_comp_nodes are not consumed yet, add dependency
                        if len(pim_comp_nodes) != 0:
                            for pim_comp in pim_comp_nodes:
                                self.add_parent(send_output_node, pim_comp)
                                pim_comp_nodes = []
                        if layers[layer_end - 1].comm_type != "NONE" and use_comm:
                            self.add_parent(output_store_node, comm_coll_node)
                        elif layers[layer_end - 1].comp_node != None:
                            self.add_parent(output_store_node, comp_node)
                        else:
                            self.add_parent(output_store_node, layers[layer_end - 2].comp_node)
                        encode_message(g, output_store_node)
                    else:
                        if layers[layer_end - 1].is_expert or layers[layer_end - 1].is_pim:
                            # Send output (to the next layer in another npu group)
                            send_output_node = self.get_comm_node(
                                is_send=True,
                                layer_name=layers[layer_end].name,
                                comm_type=layers[layer_end].comm_type,
                                comm_size=layers[layer_end].input_memory_size,
                                comm_src=npu_id,
                                comm_dst=npu_id + npus_per_group
                            )
                        else:
                            send_output_node = self.get_comm_node(
                                is_send=True,
                                layer_name=layers[layer_end - 1].name,
                                comm_type=layers[layer_end - 1].comm_type,
                                comm_size=layers[layer_end - 1].output_memory_size,
                                comm_src=npu_id,
                                comm_dst=npu_id + npus_per_group
                            )
                        # if pim_comp_nodes are not consumed yet, add dependency
                        if len(pim_comp_nodes) != 0:
                            for pim_comp in pim_comp_nodes:
                                self.add_parent(send_output_node, pim_comp)
                                pim_comp_nodes = []
                        if layers[layer_end - 1].comm_type != "NONE" and use_comm:
                            self.add_parent(send_output_node, comm_coll_node)
                        elif layers[layer_end - 1].comp_node != None:
                            self.add_parent(send_output_node, comp_node)
                        else:
                            self.add_parent(send_output_node, layers[layer_end - 2].comp_node)
                        encode_message(g, send_output_node)
    
    def convert_prefill(self, f: TextIOWrapper, num_layers: int, num_npu_group: int,
                        stage_boundaries: List[int] = None):
        layers: list[Layer] = self.get_layers(f)
        # There will be no pim operation in prefill (PIM cannot perform GEMM)

        # vllm: check eviction or load
        evict = None
        load = None
        ev_ld_cnt = 0
        for i in range(2):
            if 'kv_load' in layers[i].name:
                load = self.get_memory_load_node(
                            layers[i].name,
                            "WEIGHT",
                            layers[i].weight_memory_loc,
                            layers[i].weight_memory_size, # already per npu kv_cache size
                        )
            elif 'kv_evict' in layers[i].name:
                evict = self.get_memory_store_node(
                            layers[i].name,
                            "WEIGHT",
                            layers[i].weight_memory_loc,
                            layers[i].weight_memory_size,
                        )
            else:
                continue
            ev_ld_cnt += 1
            
        layers = layers[ev_ld_cnt:]
        num_layers -= ev_ld_cnt

        if self.num_npus % num_npu_group != 0: print("Warning! num_npus % num_npu_group != 0, Some npus won't do anything!")
        npus_per_group = self.num_npus // num_npu_group
        if npus_per_group == 1: # same as pipeline parallelism, ignore all reduce
            use_comm = False
        else:
            use_comm = True
        stage_edges = self.get_stage_edges(num_layers, num_npu_group,
                                           stage_boundaries or [])

        actual_receiver_streams = {}
        if self.pd_decode_offset is not None:
            if self.pd_decode_tp is None or self.pd_decode_tp < 1:
                raise ValueError(
                    "Explicit P/D receiver graphs require pd_decode_tp")
            decode_pp = int(self.pd_decode_pp or 1)
            for decode_rank in range(
                    int(self.pd_decode_offset),
                    int(self.pd_decode_offset) + int(self.pd_decode_tp) * decode_pp):
                receiver_filename = "%s.%d.et" % (
                    self.output_filename, decode_rank)
                receiver = open(receiver_filename, "wb")
                encode_message(receiver, self.get_global_metadata())
                actual_receiver_streams[decode_rank] = receiver

        for npu_group in range(num_npu_group):
            for npu_offset in range(npus_per_group):
                # Re-read the authoritative edges per rank: the walk below may
                # rebind layer_end if it ever overruns.
                layer_start, layer_end = stage_edges[npu_group]
                npu_id = npu_group * npus_per_group + npu_offset + self.npu_offset
                output_filename1 = "%s.%d.et" % (self.output_filename, npu_id)
                output_filename2 = "%s.%d.et" % (self.output_filename, npu_id + self.num_npus) # sender for prefill-decode
                if self.pd_decode_offset is not None:
                    # ConfigBuilder reserves a legacy shadow-rank range after
                    # each Prefill instance. Serving/FlowSim still polls those
                    # ranks as members of the Prefill batch, so emit an empty
                    # graph for compatibility. Actual P2D communication is
                    # represented only by the sender nodes below, addressed
                    # to the real Decode ranks; these files contain no RECVs
                    # and cannot complete or duplicate KV traffic.
                    with open(output_filename2, "wb") as shadow:
                        encode_message(shadow, self.get_global_metadata())
                first_comp_node = True
                comp_node = None
                # Explicit P/D mode sends directly to the real Decode rank;
                # it must not create a second synthetic receiver graph.  The
                # null context keeps the legacy shadow path byte-for-byte
                # compatible while making the actual-rank path rectangular
                # only over real serving ranks.
                receiver_context = (
                    open(output_filename2, "wb")
                    if self.pd_decode_offset is None
                    else nullcontext(None)
                )
                with open(output_filename1, "wb") as g, receiver_context as s:
                    global_metadata = self.get_global_metadata()
                    encode_message(g, global_metadata)
                    if s is not None:
                        encode_message(s, global_metadata)
                    if evict != None:
                        encode_message(g, evict)
                    if load != None:
                        encode_message(g, load)
                    if npu_group == 0:
                        # Load Input
                        input_load_node = self.get_memory_load_node(
                            layers[layer_start].name,
                            "INPUT",
                            layers[layer_start].input_memory_loc,
                            layers[layer_start].input_memory_size,
                        )
                        encode_message(g, input_load_node)                  
                    else:
                        if layers[layer_start].is_expert:
                            # Receive input (from the previous layer in another npu group)
                            receive_input_node = self.get_comm_node(
                                is_send=False,
                                layer_name=layers[layer_start-1].name,
                                comm_type=layers[layer_start-1].comm_type,
                                comm_size=layers[layer_start-1].output_memory_size,
                                comm_src=npu_id - npus_per_group,
                                comm_dst=npu_id
                            )
                            encode_message(g, receive_input_node)
                        else:
                            # Receive input (from the previous layer in another npu group)
                            receive_input_node = self.get_comm_node(
                                is_send=False,
                                layer_name=layers[layer_start].name,
                                comm_type=layers[layer_start].comm_type,
                                comm_size=layers[layer_start].input_memory_size,
                                comm_src=npu_id - npus_per_group,
                                comm_dst=npu_id
                            )
                            encode_message(g, receive_input_node)

                    expert_start = False
                    replicated_expert = False
                    layer_num = layer_start
                    push_last_nodes = {}
                    push_settlement_nodes = {}
                    while expert_start or layer_num < layer_end:
                        if not layers[layer_num].is_expert:
                            push = _push_marker_fields(layers[layer_num].name)
                            if push is not None:
                                request_id = int(push["r"])
                                if push["kind"] == "settlement":
                                    settlement_node = self.get_comp_node(
                                        layers[layer_num].name, 0)
                                    if 'comp_node' in locals() and comp_node is not None:
                                        self.add_parent(settlement_node, comp_node)
                                    self._add_event_metadata(
                                        settlement_node, layers[layer_num].name, layer_num)
                                    layers[layer_num].comp_node = settlement_node
                                    push_settlement_nodes[request_id] = settlement_node
                                    encode_message(g, settlement_node)
                                elif push["kind"] == "write":
                                    if layers[layer_num].comm_size <= 0:
                                        raise ValueError(
                                            "NIXL Push WRITE marker has non-positive bytes")
                                    parent_node = push_settlement_nodes.get(
                                        request_id, comp_node)
                                    if parent_node is None:
                                        raise ValueError(
                                            "NIXL Push WRITE marker has no compute parent")
                                    send_nodes = self._emit_pd_kv_sends(
                                        g,
                                        (actual_receiver_streams
                                         if self.pd_decode_offset is not None else s),
                                        parent_node, npu_group, npu_offset,
                                        npus_per_group, npu_id,
                                        layers[layer_num].comm_size, layer_num,
                                        layer_name=layers[layer_num].name)
                                    push_last_nodes.setdefault(request_id, []).extend(send_nodes)
                                    layers[layer_num].comm_node = (
                                        send_nodes[-1] if send_nodes else None)
                                else:
                                    commit_node = self.get_comp_node(
                                        layers[layer_num].name, 0)
                                    parents = push_last_nodes.get(request_id, ())
                                    if parents:
                                        for parent in parents:
                                            self.add_parent(commit_node, parent)
                                    elif 'comp_node' in locals() and comp_node is not None:
                                        self.add_parent(commit_node, comp_node)
                                    self._add_event_metadata(
                                        commit_node, layers[layer_num].name, layer_num)
                                    layers[layer_num].comp_node = commit_node
                                    encode_message(g, commit_node)
                                layer_num += 1
                                continue
                            if (self.local_offloading or layers[layer_num].weight_memory_loc != "LOCAL") and layers[layer_num].weight_memory_size > 0:
                                # Load weight (for weight offloading)
                                weight_load_node = self.get_memory_load_node(
                                    layers[layer_num].name,
                                    "WEIGHT",
                                    layers[layer_num].weight_memory_loc,
                                    layers[layer_num].weight_memory_size,
                                )
                                layers[layer_num].weight_memory_node = weight_load_node
                                if expert_start:
                                    self.add_parent(weight_load_node, comp_node) # dependent to previous comp_node due to gate function
                                encode_message(g, weight_load_node)
                            
                            # Compute
                            if layers[layer_num].comp_time != 0:
                                comp_node = self.get_comp_node(
                                    layers[layer_num].name, 
                                    layers[layer_num].comp_time)
                                layers[layer_num].comp_node = comp_node

                                if first_comp_node:
                                    if npu_group == 0:
                                        self.add_parent(comp_node, input_load_node)
                                    else:
                                        self.add_parent(comp_node, receive_input_node)
                                    if evict != None:
                                        self.add_parent(comp_node, evict)
                                    if load != None:
                                        self.add_parent(comp_node, load)
                                    if layers[layer_num].weight_memory_node != None:
                                        self.add_parent(comp_node, layers[layer_num].weight_memory_node)
                                    first_comp_node = False
                                else:
                                    if layers[layer_num].weight_memory_node != None:
                                        self.add_parent(comp_node, layers[layer_num].weight_memory_node)
                                    if layers[layer_num - 1].comm_node != None:
                                        self.add_parent(comp_node, layers[layer_num - 1].comm_node)
                                    elif layers[layer_num - 1].comp_node != None:
                                        self.add_parent(comp_node, layers[layer_num - 1].comp_node)
                                    else:
                                        self.add_parent(comp_node, layers[layer_num - 2].comp_node)
                                
                                encode_message(g, comp_node)

                                # Send KV cache after each kv_proj in the
                                # upstream-compatible LAYERWISE realization.
                                # comm_size comes from the trace's comm_size
                                # column, which the frontend fills with the
                                # per-layer, per-rank K+V bytes. It used to read
                                # output_memory_size, i.e. the whole QKV
                                # activation, which shipped Q as well and
                                # overstated the transfer by
                                # (q_dim + 2*kv_dim) / (2*kv_dim) -- 3x for
                                # Llama-3.1-8B -- and ignored kv_cache_dtype.
                                if "v_proj" in layers[layer_num].name and layers[layer_num].comm_size > 0:
                                    self._emit_pd_kv_sends(
                                        g,
                                        (actual_receiver_streams
                                         if self.pd_decode_offset is not None else s),
                                        comp_node, npu_group, npu_offset,
                                        npus_per_group, npu_id,
                                        layers[layer_num].comm_size, layer_num)

                            # POST_PREFILL traces append this zero-time marker
                            # after sampler.  It carries the same model-derived
                            # K/V bytes as all LAYERWISE sends combined, but
                            # creates one post-prefill cache-chunk transfer.
                            if (layers[layer_num].name.startswith("pd_kv_transfer") and
                                    layers[layer_num].comm_size > 0):
                                if first_comp_node:
                                    raise ValueError(
                                        "POST_PREFILL P2D KV marker precedes "
                                        "all prefill computation"
                                    )
                                self._emit_pd_kv_sends(
                                    g,
                                    (actual_receiver_streams
                                     if self.pd_decode_offset is not None else s),
                                    comp_node, npu_group, npu_offset,
                                    npus_per_group, npu_id,
                                    layers[layer_num].comm_size, layer_num)

                            # Communication (if required)
                            if layers[layer_num].comm_type != "NONE" and use_comm:
                                comm_coll_node = self.get_comm_coll_node(layers[layer_num].name, layers[layer_num].comm_type, layers[layer_num].comm_size, layers[layer_num].involved_dim, layer_num)
                                # for j in range(self.num_dims):
                                # comm_coll_node.involved_dim.append(True)
                                layers[layer_num].comm_node = comm_coll_node
                                if layers[layer_num].comp_time != 0:
                                    self.add_parent(comm_coll_node, comp_node)
                                encode_message(g, comm_coll_node)
                            # add layer_num
                            layer_num += 1
                        # expert layer starts
                        elif layers[layer_num].is_expert:
                            # communication can happen even with one NPU in the group, for example, expert input gathering in data parallel
                            if not expert_start:
                                replicated_expert = self._replicated_single_expert(layers, layer_num)
                            if expert_start == False and layers[layer_num].comm_size > 0 and layers[layer_num].comm_type != "NONE": 
                                # Start of expert communication before expert computation.
                                comm_coll_node = self.emit_expert_communication(
                                    g, layers[layer_num], "expert_start", comp_node,
                                    npu_id, layer_num)
                                layers[layer_num].comm_node = comm_coll_node
                            expert_start = True
                            # check expert end
                            if layers[layer_num].expert_num == 'END':
                                expert_start = False
                                layers[layer_num].comp_node = comp_node # is latest comp_node
                                # End of expert communication after expert computation.
                                if layers[layer_num].comm_size > 0 and layers[layer_num].comm_type != "NONE":
                                    comm_coll_node = self.emit_expert_communication(
                                        g, layers[layer_num], "expert_end", comp_node,
                                        npu_id, layer_num)
                                    layers[layer_num].comm_node = comm_coll_node
                                layer_num += 1
                                continue
                            # round robin assignment
                            expert_id = int(layers[layer_num].expert_num) % npus_per_group
                            if not replicated_expert and npu_offset != expert_id:
                                # go to next expert
                                while True:
                                    layer_num += 1
                                    if layers[layer_num].is_expert:
                                        break
                            else:
                                layers[layer_num].comp_node = comp_node # is latest comp_node
                                layer_num += 1

                    # The frontend cuts stages on transformer-block boundaries,
                    # so the walk above lands exactly on the stage edge. Expert
                    # and PIM blocks live inside a block and can no longer be
                    # straddled; warn loudly if that ever stops holding.
                    if layer_num != layer_end:
                        print(f"Warning! pipeline stage {npu_group} walked to "
                              f"layer {layer_num}, expected {layer_end}")
                        layer_end = layer_num

                    if (npu_group == (num_npu_group - 1) and
                            self.pd_decode_offset is None):
                        # Send output (for the last layer, to the paired decode npu)
                        send_output_node = self.get_comm_node(
                            is_send=True,
                            layer_name=layers[layer_end - 1].name,
                            comm_type=layers[layer_end - 1].comm_type,
                            comm_size=layers[layer_end - 1].output_memory_size,
                            comm_src=npu_id,
                            comm_dst=npu_id + self.num_npus
                        )
                        if layers[layer_end - 1].comm_type != "NONE" and use_comm:
                            self.add_parent(send_output_node, comm_coll_node)
                        elif layers[layer_end - 1].comp_node != None:
                            self.add_parent(send_output_node, comp_node)
                        else:
                            self.add_parent(send_output_node, layers[layer_end - 2].comp_node)
                        encode_message(g, send_output_node)
                        # paired decode npu receive output
                        recv_output_node = self.get_comm_node(
                            is_send=False,
                            layer_name=layers[layer_end - 1].name,
                            comm_type=layers[layer_end - 1].comm_type,
                            comm_size=layers[layer_end - 1].output_memory_size,
                            comm_src=npu_id,
                            comm_dst=npu_id + self.num_npus
                        )
                        encode_message(s, recv_output_node)
                    elif npu_group == (num_npu_group - 1):
                        # With an explicit decode offset the prefill sender
                        # has no shadow-rank output message; the Python
                        # serving layer transfers request state separately.
                        pass
                    else:
                        if layers[layer_end - 1].is_expert:
                            # Send output (to the next layer in another npu group)
                            send_output_node = self.get_comm_node(
                                is_send=True,
                                layer_name=layers[layer_end].name,
                                comm_type=layers[layer_end].comm_type,
                                comm_size=layers[layer_end].input_memory_size,
                                comm_src=npu_id,
                                comm_dst=npu_id + npus_per_group
                            )
                        else:
                            send_output_node = self.get_comm_node(
                                is_send=True,
                                layer_name=layers[layer_end - 1].name,
                                comm_type=layers[layer_end - 1].comm_type,
                                comm_size=layers[layer_end - 1].output_memory_size,
                                comm_src=npu_id,
                                comm_dst=npu_id + npus_per_group
                            )
                        if layers[layer_end - 1].comm_type != "NONE" and use_comm:
                            self.add_parent(send_output_node, comm_coll_node)
                        elif layers[layer_end - 1].comp_node != None:
                            self.add_parent(send_output_node, comp_node)
                        else:
                            self.add_parent(send_output_node, layers[layer_end - 2].comp_node)
                        encode_message(g, send_output_node)

        for receiver in actual_receiver_streams.values():
            receiver.close()

    def convert_event(self, f: TextIOWrapper, num_layers: int):
        layers: list[Layer] = self.get_layers(f)
        for npu_id in range(self.num_npus):
            output_filename = "%s.%d.et" % (self.output_filename, npu_id)
            with open(output_filename, "wb") as g:
                global_metadata = self.get_global_metadata()
                encode_message(g, global_metadata)
                for idx, layer in enumerate(layers):
                    comp_node = self.get_comp_node(
                    layer.name, 
                    layer.comp_time)
                    layer.comp_node = comp_node
                    encode_message(g, comp_node)

    def convert(self):
        with open(self.input_filename, "r") as f:
            first_line = f.readline().strip().split()
            execution_type = first_line[0]

            # The first line carries "key: value" pairs after the execution
            # type, e.g. "model_parallel_NPU_group: 4  pp_stage_boundaries: 73,145,217".
            header = {}
            fields = first_line[1:]
            for i in range(0, len(fields) - 1, 2):
                if fields[i].endswith(":"):
                    header[fields[i][:-1]] = fields[i + 1]

            num_npu_group = int(header.get("model_parallel_NPU_group", 0))
            boundary_str = header.get("pp_stage_boundaries", "")
            stage_boundaries = (
                [int(b) for b in boundary_str.split(",")] if boundary_str else []
            )

            second_line = f.readline().strip()
            num_layers = int(second_line)

            third_line = f.readline() # This is for the table header, so just ignore it

            if execution_type == "COLOCATED":
                if num_npu_group <= 0:
                    raise ValueError(f"model_parallel_NPU_group <= 0")
                self.convert_common(f, num_layers, num_npu_group, stage_boundaries)
            elif execution_type == "PREFILL":
                if num_npu_group <= 0:
                    raise ValueError(f"model_parallel_NPU_group <= 0")
                self.convert_prefill(f, num_layers, num_npu_group, stage_boundaries)
            elif execution_type == "DECODE":
                if num_npu_group <= 0:
                    raise ValueError(f"model_parallel_NPU_group <= 0")
                self.convert_common(f, num_layers, num_npu_group, stage_boundaries)
            elif execution_type == "EVENT":
                self.convert_event(f, num_layers)
            else:
                raise ValueError(f"Unsupported execution type, {execution_type}")
