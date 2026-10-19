import bisect
import hashlib
import json
import pandas as pd
from time import perf_counter_ns, time
import csv
import os

from .request import *
from .utils import *
from .controller import *
from .memory_model import *
from .graph_generator import *
from .trace_generator import *
from .logger import print_markup, print_rule
from .pim_model import *
import numpy as np

# class that shedules request of astra-sim
class Scheduler:
    """vLLM V1-style continuous batching over a per-tier block pool.

    Shape follows ``vllm/v1/core/sched/scheduler.py`` (v0.19.0): a persistent
    ``running`` set is served first, preempting only from its own tail, then the
    ``waiting`` queue is admitted while budget and slots remain -- never by
    preempting. A step that preempted skips admission entirely, which is what
    keeps the running set from oscillating.

    There is one ``schedule()`` for prefix caching on and off. The pool handles
    ``enable_caching=False`` the way vLLM does (allocate through the same free
    list, never index), so the two separate schedulers this file used to carry
    had no reason to exist -- and their drifting apart was its own source of bugs.
    """

    def __init__(self, model, node_id, instance_id, max_num_seqs, max_num_batched_tokens,
                 num_npus, tp_size, pp_size, npu_mem, cpu_mem,
                 start_npu, pd_type, fp, block_size, req_num,
                 enable_prefix_caching, enable_prefix_sharing, prefix_pool, prefix_storage,
                 enable_chunked_prefill=False,
                 long_prefill_token_threshold=0, cxl_mem=0, ep_size=1, kv_cache_dtype='auto',
                 npu_memory_utilization=1.0, reserve_full_isl=True,
                 actual_pd_receivers=False,
                 research_decode_phase_delay_ns=0,
                 destination_prefix_handoff="DISABLED",
                 pd_handoff_capacity_reservation=False,
                 pd_handoff_admission="EARLY"):
        self.model = model
        self.config = get_config(model)
        self.node_id = node_id
        self.instance_id = instance_id
        self.max_num_seqs = int(max_num_seqs)
        self.max_num_batched_tokens = min(max_num_batched_tokens, self.config['max_position_embeddings'])
        self.long_prefill_token_threshold = long_prefill_token_threshold
        self.num_npus = num_npus
        self.tp_size = tp_size
        self.pp_size = pp_size
        self.fp = int(fp)
        self.kv_cache_dtype = str(kv_cache_dtype)
        self.req_num = req_num
        self.start_npu = start_npu
        self.pd_type = pd_type
        self.actual_pd_receivers = bool(actual_pd_receivers)
        self.research_decode_phase_delay_ns = max(
            0, int(research_decode_phase_delay_ns))
        self.research_decode_phase_gate_until_ns = None
        self.research_decode_phase_gate_open = False
        self.destination_prefix_handoff = str(
            destination_prefix_handoff).upper()
        if self.destination_prefix_handoff not in (
                "DISABLED", "QUERY", "DELTA"):
            raise ValueError(
                "destination_prefix_handoff must be DISABLED, QUERY, or DELTA")
        self.destination_decode_scheduler = None
        self.pd_handoff_capacity_reservation = bool(
            pd_handoff_capacity_reservation)
        self.pd_handoff_admission = str(pd_handoff_admission).upper()
        if self.pd_handoff_admission not in ("EARLY", "TWO_STAGE_FIFO"):
            raise ValueError("unknown P/D handoff admission mode")
        if self.pd_handoff_admission == "TWO_STAGE_FIFO" and self.pd_type == "prefill":
            if not self.pd_handoff_capacity_reservation:
                raise ValueError("two-stage handoff requires D capacity reservation")
            if self.tp_size != 1 or self.pp_size != 1:
                raise ValueError("two-stage handoff currently requires TP1/PP1")
            if self.destination_prefix_handoff not in ("DISABLED", "DELTA"):
                raise ValueError("two-stage handoff supports DISABLED or DELTA")
        self.enable_prefix_caching = enable_prefix_caching
        self.enable_prefix_sharing = enable_prefix_sharing
        self.enable_chunked_prefill = enable_chunked_prefill
        self.prefix_storage = prefix_storage
        # vLLM's scheduler_reserve_full_isl, True by default there: admit a
        # request only if its whole sequence fits, not merely its first chunk.
        self.reserve_full_isl = reserve_full_isl

        # Requests admitted and still generating. Persistent across steps: this
        # is what gives the scheduler a notion of "already running", which the
        # old single re-derived pool did not have.
        self.running = []
        # Not yet admitted, sorted by (arrival, id). A preempted request is
        # prepended, as in vLLM's waiting.prepend_request().
        self.waiting = []
        self.inflight = []
        # Completed Prefills retain their P KV blocks until a receiver credit
        # is available and a separate P2D transfer graph has finished.
        self.source_held = []
        self.done = []
        self.batch_ids = -1

        # Tokens recomputed because a request was preempted, and how many
        # preemptions happened. Both are reported: in the prefix-caching-off mode
        # a large recompute count is expected and is what that mode costs, while
        # in the prefix-caching modes it should stay near zero.
        self.recompute_tokens = 0
        self.num_preemptions = 0

        self.memory = MemoryModel(model, instance_id, node_id, num_npus, tp_size, npu_mem, cpu_mem,
                                  block_size, fp, enable_prefix_caching, enable_prefix_sharing,
                                  prefix_pool, prefix_storage, cxl_mem, ep_size=ep_size,
                                  pp_size=pp_size, kv_cache_dtype=kv_cache_dtype,
                                  npu_memory_utilization=npu_memory_utilization)
        self.kv = self.memory.kv

        self.logger = get_logger(self.__class__, node_id=node_id, instance_id=instance_id)
        self.research_event_path = os.environ.get(
            "SERVING_BATCH_MISS_EVENT_LOG")

    # ==================== scheduling ====================

    def schedule(self, current, sys, batch_id=-1):
        if sys != self.start_npu:
            return self._schedule_existing(sys, batch_id)

        self._record_research_event(
            "SCHEDULER_DECISION", current,
            rank=int(sys),
            running_request_ids=[int(req.id) for req in self.running],
            waiting_requests=[{
                "request_id": int(req.id),
                "status": req.status.name,
                "arrival_ns": int(req.arrival),
                "decode_ready_ns": int(getattr(
                    req, "decode_eligible_time_ns", -1)),
            } for req in self.waiting],
            inflight_batch_ids=[int(item.batch_id) for item in self.inflight],
            active_sequences=len(self.running),
            max_num_seqs=self.max_num_seqs,
            free_kv_blocks=self._free_kv_blocks_for_telemetry(),
            total_kv_blocks=self._total_kv_blocks_for_telemetry(),
            max_num_batched_tokens=self.max_num_batched_tokens)

        # The start NPU is a joiner too, and it has to try joining *before* the
        # pipeline-depth cap below. With DP groups any NPU of the instance may
        # open a round -- the idle-member dummy in particular -- and ``add_done``
        # only completes a batch once ``start_npu`` has run it, so a batch opened
        # by another NPU would otherwise never finish and the group's collective
        # would block forever. Gating the join on a *full* pipeline missed
        # exactly that case: a dummy opened by a non-start NPU leaves
        # ``pp_size - 1`` slots free, so the start NPU took the build path
        # instead, found nothing to build (its member is idle) and answered
        # "pass" forever. Joining never adds a batch, so it cannot breach the cap.
        #
        # For a non-DP instance every in-flight batch was built here, so
        # ``start_npu`` is already in ``fired``, this returns None, and the cap
        # below decides exactly as it did before.
        existing = self._schedule_existing(sys, batch_id)
        if existing is not None:
            self._record_research_event(
                "JOIN_EXISTING_BATCH", current,
                rank=int(sys), batch_id=int(existing.batch_id),
                request_ids=[int(req.id) for req in existing.requests])
            return existing

        # One batch in flight per pipeline stage: vLLM's ``batch_queue``, whose
        # maxlen is ``max_concurrent_batches`` == ``pipeline_parallel_size``.
        if len(self.inflight) >= self.pp_size:
            self._record_research_event(
                "NO_BATCH_PIPELINE_CAPACITY", current,
                rank=int(sys), inflight_batch_ids=[
                    int(item.batch_id) for item in self.inflight],
                pipeline_capacity=int(self.pp_size))
            return None

        if self.pd_type == "prefill" and self.pd_handoff_admission == "TWO_STAGE_FIFO":
            handoff = self._schedule_held_handoff(current, sys)
            if handoff is not None:
                return handoff

        token_budget = self.max_num_batched_tokens
        # (request, tokens scheduled, num_computed_tokens before this step)
        scheduled = []
        preempted = []

        token_budget = self._schedule_running(scheduled, preempted, token_budget)
        # vLLM skips the whole waiting phase on any step that preempted
        # (`if not preempted_reqs:`). Without that the running set oscillates
        # preempt -> refill -> preempt.
        if not preempted:
            token_budget = self._schedule_waiting(current, scheduled, token_budget)

        if not scheduled:
            self._record_research_event(
                "NO_BATCH_SELECTED", current,
                rank=int(sys), running_request_ids=[
                    int(req.id) for req in self.running],
                waiting_request_ids=[int(req.id) for req in self.waiting],
                active_sequences=len(self.running),
                max_num_seqs=self.max_num_seqs,
                free_kv_blocks=self._free_kv_blocks_for_telemetry(),
                remaining_token_budget=int(token_budget))
            return None
        return self._build_batch(current, sys, scheduled)

    def _record_research_event(self, event, timestamp_ns, **fields):
        """Append opt-in scheduler boundary telemetry for small research runs."""
        research_event_path = getattr(self, "research_event_path", None)
        if not research_event_path:
            return
        row = {
            "event": str(event),
            "timestamp_ns": int(timestamp_ns),
            "node_id": int(self.node_id),
            "instance_id": int(self.instance_id),
            "pd_type": str(self.pd_type),
        }
        row.update(fields)
        parent = os.path.dirname(research_event_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(research_event_path, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")

    def _free_kv_blocks_for_telemetry(self):
        """Return a best-effort KV capacity snapshot for opt-in research logs.

        Unit tests and external integrations may provide a minimal KV stub
        without the production block-pool interface. Telemetry must not make
        those otherwise-valid paths fail.
        """
        pool = getattr(self.kv, "npu_pool", None)
        getter = getattr(pool, "get_num_free_blocks", None)
        return int(getter()) if callable(getter) else None

    def _total_kv_blocks_for_telemetry(self):
        pool = getattr(self.kv, "npu_pool", None)
        value = getattr(pool, "num_blocks", None)
        return int(value) if value is not None else None

    def _prefix_cache_compatibility_key(self):
        """Identity/layout guard for cross-stage prefix block reuse."""
        config_digest = hashlib.sha256(json.dumps(
            self.config, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")).hexdigest()
        return (
            str(self.model), config_digest, int(self.tp_size), int(self.pp_size),
            int(self.fp), str(self.kv_cache_dtype), int(self.kv.block_size),
            int(self.config.get("num_hidden_layers", 0)),
            int(self.config.get("num_key_value_heads", 0)),
            int(self.config.get("head_dim", 0)),
        )

    def _query_or_reserve_destination_prefix(self, req, current):
        """Query a paired Decode cache before P2D flow construction.

        QUERY is diagnostic only. DELTA atomically pins matching NPU prefix
        blocks and reserves the remaining Decode slots; any miss, incompatibility
        or capacity failure leaves the caller on full-transfer fallback.
        Control-plane wall time is telemetry only, not serving simulation time.
        """
        if (self.pd_type != "prefill" or
                self.destination_prefix_handoff == "DISABLED" or
                req.destination_prefix_query_checked):
            return
        req.destination_prefix_query_checked = True
        destination_id = getattr(req, "paired_decode_instance_id", None)
        peers = getattr(self, "destination_decode_schedulers", {})
        peer = (peers.get(int(destination_id))
                if destination_id is not None else
                self.destination_decode_scheduler)
        if peer is None:
            self._record_research_event(
                "DEST_PREFIX_QUERY", current, request_id=int(req.id),
                status="NO_PAIRED_DECODE", simulated_duration_ns=0)
            self._record_research_event(
                "DEST_PREFIX_QUERY_COMPLETE", current,
                request_id=int(req.id), status="NO_PAIRED_DECODE",
                control_wall_ns=0, simulated_duration_ns=0)
            return

        started = perf_counter_ns()
        source_key = self._prefix_cache_compatibility_key()
        destination_key = peer._prefix_cache_compatibility_key()
        if source_key != destination_key:
            req.destination_prefix_control_wall_ns = perf_counter_ns() - started
            self._record_research_event(
                "DEST_PREFIX_QUERY", current, request_id=int(req.id),
                destination_instance_id=int(peer.instance_id),
                status="INCOMPATIBLE_LAYOUT", hit_tokens=0,
                simulated_duration_ns=0,
                control_wall_ns=int(req.destination_prefix_control_wall_ns))
            self._record_research_event(
                "DEST_PREFIX_QUERY_COMPLETE", current,
                request_id=int(req.id), status="INCOMPATIBLE_LAYOUT",
                control_wall_ns=int(req.destination_prefix_control_wall_ns),
                simulated_duration_ns=0)
            return

        prior_pool = req.storage_hit_pool
        prior_blocks = req.storage_hit_blocks
        try:
            blocks, npu_hit, lower_hit = peer.kv.get_computed_blocks(req)
        finally:
            # Prefix lookup on another tier must not overwrite Prefill's
            # pending lower-tier recall bookkeeping on this shared Request.
            req.storage_hit_pool = prior_pool
            req.storage_hit_blocks = prior_blocks

        status = "HIT" if npu_hit else ("LOWER_TIER_ONLY" if lower_hit else "MISS")
        self._record_research_event(
            "DEST_PREFIX_QUERY", current, request_id=int(req.id),
            destination_instance_id=int(peer.instance_id), status=status,
            hit_tokens=int(npu_hit), lower_tier_hit_tokens=int(lower_hit),
            block_ids=[int(block.block_id) for block in blocks],
            simulated_duration_ns=0)

        if self.destination_prefix_handoff != "DELTA" or npu_hit <= 0:
            req.destination_prefix_control_wall_ns = perf_counter_ns() - started
            self._record_research_event(
                "DEST_PREFIX_QUERY_COMPLETE", current,
                request_id=int(req.id),
                destination_instance_id=int(peer.instance_id),
                status=status, hit_tokens=int(npu_hit),
                control_wall_ns=int(req.destination_prefix_control_wall_ns),
                simulated_duration_ns=0)
            return

        reservation = peer.kv.reserve_handoff_prefix(req, destination_key)
        req.destination_prefix_control_wall_ns = perf_counter_ns() - started
        if reservation is None:
            self._record_research_event(
                "DEST_PREFIX_RESERVATION_FAILED", current,
                request_id=int(req.id),
                destination_instance_id=int(peer.instance_id),
                reason="CAPACITY_OR_RACE_FALLBACK_FULL",
                simulated_duration_ns=0,
                control_wall_ns=int(req.destination_prefix_control_wall_ns))
            return

        req.destination_prefix_reuse_tokens = int(reservation["hit_tokens"])
        req.destination_prefix_reservation = {
            "destination_instance_id": int(peer.instance_id),
            "hit_tokens": int(reservation["hit_tokens"]),
            "required_blocks": int(reservation["required_blocks"]),
        }
        self._record_research_event(
            "DEST_PREFIX_RESERVED", current,
            request_id=int(req.id),
            destination_instance_id=int(peer.instance_id),
            hit_tokens=int(reservation["hit_tokens"]),
            required_blocks=int(reservation["required_blocks"]),
            simulated_duration_ns=0,
            control_wall_ns=int(req.destination_prefix_control_wall_ns))

    def _reserve_destination_handoff_capacity(self, req, current):
        """Acquire Decode staging credit before a Prefill graph sends KV.

        This opt-in admission baseline blocks at the Prefill waiting queue
        when D memory is full. It avoids the invalid state in which layerwise
        P2D has already completed but the receiver has no KV blocks. The
        reservation is committed at ``add_decode`` and is owned by the D pool.
        """
        if (self.pd_type != "prefill" or
                not getattr(self, "pd_handoff_capacity_reservation", False)):
            return True
        if getattr(req, "destination_prefix_reservation", None) is not None:
            return True
        destination_id = getattr(req, "paired_decode_instance_id", None)
        peers = getattr(self, "destination_decode_schedulers", {})
        peer = (peers.get(int(destination_id))
                if destination_id is not None else
                self.destination_decode_scheduler)
        if peer is None:
            raise RuntimeError(
                "P/D handoff capacity reservation has no paired Decode "
                "scheduler for request %s" % req.id)
        reservation = peer.kv.reserve_handoff_prefix(
            req, peer._prefix_cache_compatibility_key(), allow_empty=True)
        if reservation is None:
            self._record_research_event(
                "HANDOFF_CAPACITY_WAIT", current,
                request_id=int(req.id),
                destination_instance_id=int(peer.instance_id),
                free_kv_blocks=peer.kv.npu_pool.get_num_free_blocks(),
                required_blocks=(int(req.original_input) + 1 +
                                 peer.kv.block_size - 1) // peer.kv.block_size,
                simulated_duration_ns=0)
            return False
        req.destination_prefix_reservation = {
            "destination_instance_id": int(peer.instance_id),
            "hit_tokens": int(reservation["hit_tokens"]),
            "required_blocks": int(reservation["required_blocks"]),
        }
        # Delta suppression uses only the prefix pinned by this credit.
        req.destination_prefix_reuse_tokens = (
            int(reservation["hit_tokens"])
            if self.destination_prefix_handoff == "DELTA" else 0)
        self._record_research_event(
            "HANDOFF_CAPACITY_RESERVED", current,
            request_id=int(req.id),
            destination_instance_id=int(peer.instance_id),
            hit_tokens=int(reservation["hit_tokens"]),
            required_blocks=int(reservation["required_blocks"]),
            simulated_duration_ns=0)
        return True

    def _schedule_held_handoff(self, current, sys):
        """Issue a transfer-only graph after the oldest held P KV gets D credit."""
        if not self.source_held:
            return None
        req = self.source_held[0]
        if req.id not in self.kv.req_to_blocks:
            raise RuntimeError("held source KV lost before P2D transfer")
        if not self._reserve_destination_handoff_capacity(req, current):
            return None
        self.source_held.pop(0)
        req.status = RequestStatus.RUNNING
        batch = Batch(self.get_batch_id(), self.model, 0, 0, [], [],
                      0, 0, [], [], [], current, self.kv.npu_used_bytes(),
                      pd_kv_send_tokens=int(req.original_input))
        batch.handoff_only = True
        batch.fired.append(sys)
        batch.requests.append(req)
        batch.scheduled_tokens = {req.id: 0}
        self.inflight.append(batch)
        self._record_research_event(
            "SOURCE_KV_TRANSFER_STARTED", current, request_id=int(req.id),
            batch_id=int(batch.batch_id),
            held_blocks=len(self.kv.req_to_blocks[req.id]),
            credit_blocks=int(req.destination_prefix_reservation["required_blocks"]))
        return batch

    def cancel_held_handoff(self, request_id, current):
        """Cancel a held transfer immediately, or defer release until its graph ends."""
        for index, req in enumerate(self.source_held):
            if int(req.id) == int(request_id):
                self.source_held.pop(index)
                self.kv.free(req)
                req.handoff_cancelled = True
                self._retire(req)
                self._record_research_event(
                    "SOURCE_KV_CANCELLED", current, request_id=int(req.id),
                    phase="HELD")
                return True
        for batch in self.inflight:
            if getattr(batch, "handoff_only", False) and any(
                    int(req.id) == int(request_id) for req in batch.requests):
                batch.requests[0].handoff_cancelled = True
                self._record_research_event(
                    "SOURCE_KV_CANCELLED", current,
                    request_id=int(request_id), phase="TRANSFER_INFLIGHT")
                return True
        return False

    def _schedule_running(self, scheduled, preempted, token_budget):
        """Phase A: serve requests already running, preempting from the tail."""
        i = 0
        while i < len(self.running) and token_budget > 0:
            req = self.running[i]
            num_new = self._num_new_tokens(req, token_budget)
            if num_new <= 0:
                # Nothing left to compute for this request yet. vLLM continues
                # rather than breaking here, so a later request is not blocked.
                # Legitimate only while another batch is in flight and about to
                # advance this request (pp_size > 1); otherwise nothing will ever
                # move it and the run cannot terminate, so say so loudly.
                if not any(req in b.requests for b in self.inflight):
                    raise RuntimeError(
                        f"[Scheduler] [node_id={self.node_id},inst={self.instance_id}] "
                        f"request {req.id} is running with nothing to schedule and no "
                        f"batch in flight: num_computed_tokens="
                        f"{req.num_computed_tokens}, num_tokens_reached="
                        f"{req.num_tokens_reached}, output={req.output}. This deadlocks "
                        f"the run -- num_tokens_reached was not advanced when a token "
                        f"was produced."
                    )
                i += 1
                continue

            blocks = None
            while True:
                blocks = self.kv.allocate_slots(req, num_new)
                if blocks is not None:
                    break
                # Preempt the lowest-priority running request. Under FCFS that
                # is the most recently admitted, i.e. the tail.
                victim = self.running.pop()
                self._preempt_request(victim)
                preempted.append(victim)
                if victim is req:
                    break

            if blocks is None:
                break

            scheduled.append((req, num_new, req.num_computed_tokens))
            token_budget -= num_new
            i += 1
        return token_budget

    def _schedule_waiting(self, current, scheduled, token_budget):
        """Phase B: admit from the waiting queue. Never preempts to admit."""
        while self.waiting and token_budget > 0:
            if len(self.running) >= self.max_num_seqs:
                break
            req = self.waiting[0]
            if req.arrival > current:
                # Arrival-sorted, so nothing behind it has arrived either.
                break
            eligible_time = int(getattr(req, "decode_eligible_time_ns", -1))
            if (self.pd_type == "decode" and eligible_time >= 0 and
                    eligible_time > current):
                # Research-only one-time phase gate: KV remains ready and
                # resident; only the first Decode admission is held.
                break

            num_computed = req.num_computed_tokens
            hit_blocks, num_npu_hit, num_lower_hit = [], 0, 0
            if num_computed == 0:
                hit_blocks, num_npu_hit, num_lower_hit = self.kv.get_computed_blocks(req)
                req.npu_cache_hit = num_npu_hit
                req.storage_cache_hit = num_npu_hit + num_lower_hit
                req.prefix_cache_hit = req.storage_cache_hit
                num_computed = num_npu_hit + num_lower_hit
                self._record_research_event(
                    "PREFIX_CACHE_LOOKUP", current,
                    request_id=int(req.id),
                    session_id=getattr(req, "session_id", None),
                    sub_request_index=getattr(req, "sub_request_index", None),
                    requested_tokens=int(req.original_input),
                    npu_hit_tokens=int(num_npu_hit),
                    lower_tier_hit_tokens=int(num_lower_hit),
                    total_hit_tokens=int(num_computed),
                    lookup_simulated_duration_ns=0)

            num_new = req.num_tokens - num_computed
            threshold = self.long_prefill_token_threshold
            if 0 < threshold < num_new:
                num_new = threshold
            if not self.enable_chunked_prefill and num_new > self.max_num_batched_tokens:
                raise ValueError(
                    "Request %d needs %d unsplittable tokens, exceeding "
                    "max_num_batched_tokens=%d; enable chunked prefill or "
                    "increase the token budget" %
                    (req.id, num_new, self.max_num_batched_tokens))
            if not self.enable_chunked_prefill and num_new > token_budget:
                # Cannot split this prefill, and it does not fit. Stop here
                # rather than skipping ahead, to keep FCFS.
                break
            num_new = min(num_new, token_budget)
            if num_new <= 0:
                break

            if self.reserve_full_isl and not self.kv.can_fit_full_sequence(
                    req, hit_blocks, num_npu_hit, num_lower_hit):
                # Its first chunk would fit but the whole sequence would not, so
                # admitting it now only defers a preemption. vLLM breaks here.
                break

            blocks = self.kv.allocate_slots(req, num_new, hit_blocks,
                                            num_npu_hit, num_lower_hit)
            if blocks is None:
                # vLLM breaks here: a waiting request never causes a preemption.
                break

            if getattr(self, "pd_handoff_admission", "EARLY") != "TWO_STAGE_FIFO":
                self._query_or_reserve_destination_prefix(req, current)
            if (getattr(self, "pd_handoff_admission", "EARLY") != "TWO_STAGE_FIFO" and
                    not self._reserve_destination_handoff_capacity(req, current)):
                # The local allocation is tentative until the receiver has
                # staging credit. Keep the request waiting and retry when D
                # progress releases blocks; no KV flow has been issued yet.
                self.kv.free(req)
                req.destination_prefix_query_checked = False
                req.destination_prefix_reuse_tokens = 0
                break

            self.waiting.pop(0)
            if req.num_preemptions > 0:
                # Resuming. Whatever neither tier could return has to be
                # computed again; with no lower tier that is the whole sequence.
                self.recompute_tokens += max(0, req.num_tokens_reached - num_computed)
                self.logger.info("Resuming request #%d (%d of %d tokens recovered)",
                                 req.id, num_computed, req.num_tokens_reached)
            req.num_computed_tokens = num_computed
            req.status = RequestStatus.RUNNING
            self.running.append(req)
            if self.pd_type == "decode":
                if req.decode_admit_time_ns < 0:
                    req.decode_admit_time_ns = current
                if req.decode_capacity_queue_enter_time_ns >= 0:
                    req.decode_capacity_queue_wait_ns = max(
                        0, current - req.decode_capacity_queue_enter_time_ns)
            self.memory.record_prefix_stats(req)

            scheduled.append((req, num_new, num_computed))
            token_budget -= num_new
        return token_budget

    def next_scheduler_wakeup_time(self, current):
        """Return the next time a Decode waiter can become schedulable."""
        if self.pd_type != "decode":
            return None
        deadlines = [
            int(req.decode_eligible_time_ns)
            for req in self.waiting
            if int(getattr(req, "decode_eligible_time_ns", -1)) > int(current)
        ]
        return min(deadlines) if deadlines else None

    def _num_new_tokens(self, req, token_budget):
        """Tokens to schedule for ``req`` this step, vLLM's uniform rule.

        No prefill/decode branch: a request simply catches up to the length it
        has reached. In steady-state decode that yields 1; for a resumed request
        with ``num_computed_tokens`` reset to 0 it yields the whole sequence,
        chunked by the budget.
        """
        num_new = req.num_tokens - req.num_computed_tokens
        threshold = self.long_prefill_token_threshold
        if 0 < threshold < num_new:
            num_new = threshold
        return min(num_new, token_budget)

    def _preempt_request(self, req):
        """Give up a running request's blocks so someone else can use them.

        vLLM verbatim, including resetting ``num_computed_tokens``: that is not
        "throw it away and re-prefill", it means "forget where you were and
        re-derive it from the caches". ``free_blocks`` keeps the blocks' hashes,
        so on re-admission ``get_computed_blocks`` finds whatever is still
        resident, a lower tier returns what was written down, and only the
        remainder is recomputed. Nothing here needs a special "preserve the
        decode state" path -- the tiers are what preserve it.
        """
        self.kv.preempt(req)
        req.status = RequestStatus.PREEMPTED
        req.num_computed_tokens = 0
        req.num_preemptions += 1
        self.num_preemptions += 1
        # vLLM prepends, so a preempted request is first in line to come back.
        self.waiting.insert(0, req)
        self.logger.info("Preemption of the request #%d (count %d)", req.id, req.num_preemptions)

    def _build_batch(self, current, sys, scheduled):
        """Assemble the Batch the trace generator consumes.

        Prefill-vs-decode is decided by the *scheduled token count*, not by any
        request phase flag: >1 token is a chunk, exactly 1 is a decode. That is
        what the attention profile axes want (prefill_chunk / kv_prefill vs
        n_decode / kv_decode) and how the varlen kernel sees the batch anyway. It
        is also the only classification that survives a resumed request, whose
        recomputation must be traced as a chunk even though it is past its
        original prompt length.
        """
        total_len = 0
        kv_len = 0
        num_prefill = 0
        num_decode = 0
        q_list = []
        k_list = []
        prefill_q_list = []
        prefill_k_list = []
        decode_k_list = []
        scheduled_tokens = {}
        pd_kv_send_tokens = 0
        pd_kv_send_tokens_by_request = {}

        for req, num_new, computed_before in scheduled:
            scheduled_tokens[req.id] = num_new
            total_len += num_new
            q_list.append(num_new)
            k_list.append(computed_before)
            if num_new > 1:
                num_prefill += 1
                prefill_q_list.append(num_new)
                prefill_k_list.append(computed_before)
            else:
                num_decode += 1
                kv_len += computed_before
                decode_k_list.append(computed_before)
            if req.is_init:
                req.set_que_delay(current)
                if self.pd_type == "prefill" and req.prefill_start_ns < 0:
                    req.prefill_start_ns = int(current)
                    self._record_research_event(
                        "PREFILL_STARTED", current,
                        request_id=int(req.id), batch_id=int(self.batch_ids + 1))
            if self.pd_type == "prefill":
                # Treat each release as the token interval it makes available
                # to the paired Decode. On the first chunk that interval begins
                # at token zero because a Prefill cache hit is also required on
                # the receiver unless it was independently reserved there.
                first_release = computed_before == req.prefix_cache_hit
                release_start = 0 if first_release else computed_before
                release_end = computed_before + num_new
                if first_release:
                    release_end = max(release_end, req.prefix_cache_hit)
                destination_hit = min(
                    int(getattr(req, "destination_prefix_reuse_tokens", 0)),
                    int(release_end))
                request_send_tokens = max(
                    0, int(release_end) -
                    max(int(release_start), destination_hit))
                pd_kv_send_tokens += request_send_tokens
                pd_kv_send_tokens_by_request[int(req.id)] = request_send_tokens

            # vLLM advances num_computed_tokens at schedule time
            # (_update_after_schedule), not at completion. With pp_size > 1 two
            # batches can be in flight, and advancing late would let the same
            # tokens be scheduled twice.
            req.num_computed_tokens = computed_before + num_new

        if self.pd_type == "prefill" and self.pd_handoff_admission == "TWO_STAGE_FIFO":
            pd_kv_send_tokens = 0
            pd_kv_send_tokens_by_request = {}
        recall_bytes, write_through_bytes = self.kv.take_traffic()

        batch = Batch(self.get_batch_id(), self.model, total_len, kv_len, q_list, k_list,
                      num_prefill, num_decode, prefill_q_list, prefill_k_list, decode_k_list,
                      current, self.kv.npu_used_bytes(), 0, recall_bytes,
                      pd_kv_send_tokens=pd_kv_send_tokens)
        batch.fired.append(sys)
        batch.requests.extend(req for req, _, _ in scheduled)
        batch.scheduled_tokens = scheduled_tokens
        # Written down to a victim tier off the critical path, so it carries no
        # latency -- but the bytes still cost DRAM energy.
        batch.write_through = write_through_bytes
        self.inflight.append(batch)
        selected = []
        for req, num_new, computed_before in scheduled:
            selected.append({
                "request_id": int(req.id),
                "session_id": getattr(req, "session_id", None),
                "sub_request_index": getattr(req, "sub_request_index", None),
                "scheduled_tokens": int(num_new),
                "computed_tokens_before": int(computed_before),
                "npu_cache_hit_tokens": int(getattr(req, "npu_cache_hit", 0)),
                "lower_tier_cache_hit_tokens": int(max(
                    0, getattr(req, "storage_cache_hit", 0) -
                    getattr(req, "npu_cache_hit", 0))),
                "total_prefix_cache_hit_tokens": int(getattr(
                    req, "prefix_cache_hit", 0)),
                "destination_prefix_reuse_tokens": int(getattr(
                    req, "destination_prefix_reuse_tokens", 0)),
                "p2d_kv_send_tokens": int(
                    pd_kv_send_tokens_by_request.get(int(req.id), 0)),
                "decode_ready_ns": int(getattr(
                    req, "decode_eligible_time_ns", -1)),
                "p2d_kv_ready_ns": int(getattr(
                    req, "p2d_kv_ready_time_ns", -1)),
            })
            if (self.pd_type == "decode" and
                    getattr(req, "p2d_kv_ready_time_ns", -1) >= 0 and
                    req.decode_first_batch_id < 0):
                req.decode_first_batch_id = int(batch.batch_id)
                req.decode_first_batch_decision_ns = int(current)
        self._record_research_event(
            "BATCH_SELECTED", current,
            rank=int(sys), batch_id=int(batch.batch_id),
            request_ids=[int(req.id) for req, _, _ in scheduled],
            selected_requests=selected,
            active_sequences=len(self.running),
            max_num_seqs=self.max_num_seqs,
            token_budget_used=int(sum(num for _, num, _ in scheduled)),
            pd_kv_send_tokens=int(pd_kv_send_tokens),
            pd_kv_send_tokens_by_request=pd_kv_send_tokens_by_request,
            max_num_batched_tokens=self.max_num_batched_tokens,
            free_kv_blocks=self._free_kv_blocks_for_telemetry(),
            dp_group=None)
        self.logger.info("Scheduling new batch #%d to NPU[%d]", batch.batch_id, sys)
        return batch

    def _schedule_existing(self, sys, batch_id):
        """Hand an already-formed batch to the next NPU of the instance."""
        for batch in self.inflight:
            if batch.batch_id == batch_id:
                if sys in batch.fired:
                    return None
                batch.fired.append(sys)
                self.logger.info("Scheduling existing batch #%d to NPU[%d]", batch.batch_id, sys)
                return batch
        return None

    # ==================== completion ====================

    def add_done(self, id, sys, finish):
        prompt_t = 0
        gen_t = 0
        end_reqs = []
        if len(self.inflight) == 0:
            return prompt_t, gen_t, end_reqs

        batch = None
        idx = 0
        id -= 1
        for i, b in enumerate(self.inflight):
            if b.batch_id == id:
                batch = b
                idx = i
        if batch is None or sys in batch.end:
            return prompt_t, gen_t, end_reqs

        batch.end.append(sys)
        if self.pd_type == "prefill" and self.actual_pd_receivers:
            # In actual-receiver mode every Prefill source-rank graph owns
            # model compute and its P2D SEND nodes. The old synthetic receiver
            # ranks are retained only as empty compatibility graphs; they must
            # not stand in for a missing source-rank completion.
            required_ranks = set(range(
                int(self.start_npu), int(self.start_npu) + int(self.num_npus)))
            if not required_ranks.issubset(set(batch.end)):
                return prompt_t, gen_t, end_reqs
        else:
            # Legacy P/D mode waits for the final shadow receiver rank.
            last_npu = self.num_npus * (
                2 if self.pd_type == "prefill" else 1) - 1
            if (self.start_npu not in batch.end or
                    (self.start_npu + last_npu) not in batch.end):
                return prompt_t, gen_t, end_reqs

        self.logger.info("Batch #%d is done", batch.batch_id)
        self._record_research_event(
            "BATCH_COMPLETED", finish,
            batch_id=int(batch.batch_id),
            request_ids=[int(req.id) for req in batch.requests],
            ranks_completed=sorted(int(value) for value in batch.end),
            execution_start_ns=int(getattr(batch, "execution_start_ns", -1)))

        for req in batch.requests:
            if getattr(batch, "handoff_only", False):
                if req.id not in self.kv.req_to_blocks:
                    raise RuntimeError("source KV was freed before transfer completion")
                self.kv.free(req)
                self._record_research_event(
                    "SOURCE_KV_RELEASED", finish, request_id=int(req.id),
                    batch_id=int(batch.batch_id),
                    cancelled=bool(req.handoff_cancelled))
                if req.handoff_cancelled:
                    destination_id = int(req.destination_prefix_reservation[
                        "destination_instance_id"])
                    peer = self.destination_decode_schedulers[destination_id]
                    peer.kv.free(req)
                    req.destination_prefix_reservation = None
                    self._retire(req)
                else:
                    self._retire(req)
                    end_reqs.append(req)
                continue
            if (self.pd_type == "decode" and
                    req.decode_first_batch_id == int(batch.batch_id) and
                    req.decode_first_batch_finish_ns < 0):
                req.decode_first_batch_finish_ns = int(finish)
            if req.status == RequestStatus.FINISHED:
                # With pp_size > 1 a request is legitimately in more than one
                # in-flight batch, so it can finish on an earlier batch while a
                # later one is still running. vLLM V1 skips exactly this in
                # ``update_from_output`` -- "the request is already finished.
                # This can happen if the request is aborted while the model is
                # executing it (e.g., in pipeline parallelism)" -- and drops that
                # batch's output whole, tokens included: they are past the
                # request's target, so nothing wants them.
                #
                # Without this the completion path below runs once per in-flight
                # batch: duplicate rows in the per-request CSV, req_cnt counted
                # twice, end_time and latency overwritten with the later batch's
                # clock, and a KeyError in cache_blocks, whose req_to_blocks
                # entry the first pass already freed.
                continue
            num_new = batch.scheduled_tokens[req.id]
            # num_computed_tokens was already advanced at schedule time.
            prefill_done_now = req.is_init and req.num_computed_tokens >= req.original_input

            if prefill_done_now:
                # TTFT is recorded exactly once. A resumed request has is_init
                # cleared, so it can never overwrite its own TTFT.
                req.is_init = False
                req.set_ttft(finish)
                req.first_token_visible_ns = int(finish)
                prompt_t += num_new + req.prefix_cache_hit
                if self.enable_prefix_caching:
                    self.kv.cache_blocks(req, req.num_computed_tokens)
                if self.pd_type == "prefill":
                    # The prefill instance ran through lm_head and the sampler, so
                    # the first output token exists: advance the reached length or
                    # the decode instance receives a request with nothing left to
                    # schedule (num_tokens_reached == num_computed_tokens) and
                    # deadlocks. gen_t is deliberately left to the decode side,
                    # which is where this token has always been counted.
                    req.num_tokens_reached += 1
                    self.logger.info("Request #%d is prefill done, sent to decode instance", req.id)
                    if self.pd_handoff_admission == "TWO_STAGE_FIFO":
                        req.prefill_compute_end_ns = int(finish)
                        req.status = RequestStatus.HANDOFF_WAIT
                        self.running.remove(req)
                        self.source_held.append(req)
                        self._record_research_event(
                            "PREFILL_COMPUTE_DONE_SOURCE_HELD", finish,
                            request_id=int(req.id),
                            held_blocks=len(self.kv.req_to_blocks[req.id]))
                        continue
                    self.kv.free(req)
                    self._retire(req)
                    end_reqs.append(req)
                    continue
            elif num_new > 1:
                # Chunk of a prefill, or a resumed request catching up.
                prompt_t += num_new
                if self.enable_prefix_caching:
                    self.kv.cache_blocks(req, req.num_computed_tokens)

            # A token is produced exactly when the request has caught up to the
            # length it had reached. A resumed request recomputing its history
            # has not, so it stays silent until it does.
            if req.num_computed_tokens >= req.num_tokens_reached:
                token_index = int(req.num_tokens_reached - req.original_input + 1)
                req.num_tokens_reached += 1
                gen_t += 1
                if not prefill_done_now:
                    req.add_itl(finish)
                    if (self.pd_type == "decode" and token_index == 2 and
                            req.second_token_visible_ns < 0):
                        req.second_token_visible_ns = int(finish)
                        first_visible = int(req.arrival + req.ttft)
                        req.ttst_ns = max(0, int(finish) - first_visible)
                        self._record_research_event(
                            "SECOND_TOKEN_VISIBLE", finish,
                            request_id=int(req.id),
                            token_index=2,
                            batch_id=int(batch.batch_id),
                            first_token_visible_ns=first_visible,
                            second_token_visible_ns=int(finish),
                            ttst_ns=int(req.ttst_ns),
                            first_decode_itl_ns=(
                                int(finish) - int(req.recent_end - req.itl[-1])
                                if req.itl else None))
                if self.enable_prefix_caching:
                    self.kv.cache_blocks(req, req.num_computed_tokens)

            if req.num_tokens_reached >= req.output:
                self.logger.info("Request #%d is done", req.id)
                if self.enable_prefix_caching:
                    self.kv.cache_blocks(req, req.num_computed_tokens)
                self.kv.free(req)
                req.add_latency(finish)
                self._retire(req)
                self.done.append(req)
                end_reqs.append(req)

        del self.inflight[idx]
        return prompt_t, gen_t, end_reqs

    def _retire(self, req):
        req.status = RequestStatus.FINISHED
        try:
            self.running.remove(req)
        except ValueError:
            pass

    # ==================== queue management ====================

    def get_batch_id(self):
        self.batch_ids += 1
        return self.batch_ids

    def add_request(self, req, is_init=True, paired_decode_instance_id=None):
        new_req = Request(*(req), is_init=is_init)
        new_req.paired_decode_instance_id = paired_decode_instance_id
        # Arrival order, which phase B relies on to stop at the first request
        # that has not arrived yet. Dynamically released agentic sub-requests
        # arrive mid-run, hence insort rather than append.
        bisect.insort(self.waiting, new_req, key=lambda r: (r.arrival, r.id))
        return new_req

    def add_decode(self, req, completion_time_ns=None):
        """Take over a request whose prefill ran on another instance.

        The KV transfer itself is already charged: the prefill instance's trace
        carries a per-layer send to the paired decode NPU. So this only claims
        the blocks -- reporting no load bytes, or the transfer would be billed
        twice.  A completed handoff does not bypass the Decode scheduler's
        ``max_num_seqs`` limit: when full, the request keeps its received KV
        allocation but waits in ``waiting`` until a running sequence retires.
        """
        ready_time = completion_time_ns
        if ready_time is None or ready_time < 0:
            raise ValueError(
                "P/D Decode handoff requires the simulator completion time; "
                "request arrival is not a valid KV-ready timestamp."
            )
        req.instance_id = self.instance_id
        req.status = RequestStatus.RUNNING
        req.p2d_kv_ready_time_ns = ready_time
        phase_delay_ns = int(getattr(
            self, "research_decode_phase_delay_ns", 0))
        phase_gate_open = bool(getattr(
            self, "research_decode_phase_gate_open", False))
        if phase_delay_ns > 0 and not phase_gate_open:
            gate_until = getattr(
                self, "research_decode_phase_gate_until_ns", None)
            if gate_until is None:
                gate_until = int(ready_time) + phase_delay_ns
                self.research_decode_phase_gate_until_ns = gate_until
            eligible_time = max(int(ready_time), int(gate_until))
        else:
            eligible_time = int(ready_time)
        req.decode_eligible_time_ns = eligible_time
        req.decode_phase_wait_ns = max(0, eligible_time - int(ready_time))
        req.decode_running_at_handoff = len(self.running)
        req.decode_max_num_seqs_at_handoff = self.max_num_seqs
        num_computed = req.num_computed_tokens
        reservation = getattr(req, "destination_prefix_reservation", None)
        if reservation is not None:
            if int(reservation["destination_instance_id"]) != int(self.instance_id):
                raise RuntimeError(
                    "request %s reserved Decode prefix blocks on instance %s "
                    "but was handed to instance %s" % (
                        req.id, reservation["destination_instance_id"],
                        self.instance_id))
            committed = self.kv.commit_handoff_reservation(
                req, self._prefix_cache_compatibility_key())
            if committed is None:
                raise RuntimeError(
                    "request %s issued delta P2D without a live Decode "
                    "prefix reservation" % req.id)
            self._record_research_event(
                "DEST_PREFIX_COMMIT", ready_time,
                request_id=int(req.id), hit_tokens=int(committed["hit_tokens"]),
                required_blocks=int(committed["required_blocks"]),
                requested_tokens=int(req.original_input),
                status="COMMITTED_AFTER_P2D",
                simulated_duration_ns=0)
        else:
            hit_blocks, num_npu_hit, num_lower_hit = self.kv.get_computed_blocks(req)
            self._record_research_event(
                "DECODE_PREFIX_CACHE_LOOKUP", ready_time,
                request_id=int(req.id),
                npu_hit_tokens=int(num_npu_hit),
                lower_tier_hit_tokens=int(num_lower_hit),
                total_hit_tokens=int(num_npu_hit + num_lower_hit),
                requested_tokens=int(req.original_input),
                note="post-P2D lookup; only pre-reserved hits may suppress bytes")
            # The Prefill request carries its already-computed prompt count
            # across handoff. Cache hits identify block objects to adopt; they
            # are not extra computed tokens. P2D already delivered all missing
            # data, so neither NPU nor lower-tier hit length is added here.
            if self.kv.allocate_slots(req, 1, hit_blocks, 0, 0) is None:
                raise RuntimeError(
                    f"[Scheduler] [node_id={self.node_id},inst={self.instance_id}] decode "
                    f"instance cannot admit request {req.id}: {req.num_tokens_reached} tokens "
                    f"need more blocks than the pool has free "
                    f"({self.kv.npu_pool.get_num_free_blocks()} of {self.kv.npu_pool.num_blocks})"
                )
        req.num_computed_tokens = num_computed
        self.kv.take_traffic()          # a P/D handoff is not a recall
        self._record_research_event(
            "P2D_READY", ready_time,
            request_id=int(req.id),
            paired_decode_instance_id=getattr(
                req, "paired_decode_instance_id", None),
            active_sequences=len(self.running),
            max_num_seqs=self.max_num_seqs,
            free_kv_blocks=self._free_kv_blocks_for_telemetry(),
            total_kv_blocks=self._total_kv_blocks_for_telemetry())
        phase_waiting = eligible_time > int(ready_time)
        if len(self.running) >= self.max_num_seqs or phase_waiting:
            req.status = RequestStatus.WAITING
            req.decode_capacity_queue_enter_time_ns = (
                ready_time if len(self.running) >= self.max_num_seqs else -1)
            self._enqueue_decode_handoff(req)
            self._record_research_event(
                "DECODE_PHASE_WAIT" if phase_waiting else "DECODE_CAPACITY_WAIT",
                ready_time,
                request_id=int(req.id),
                decode_eligible_time_ns=eligible_time,
                phase_wait_ns=req.decode_phase_wait_ns,
                active_sequences=len(self.running),
                max_num_seqs=self.max_num_seqs,
                free_kv_blocks=self._free_kv_blocks_for_telemetry())
            self.logger.info(
                "Decode handoff request #%d queued at %d (eligible=%d): active=%d capacity=%d",
                req.id, ready_time, eligible_time, len(self.running),
                self.max_num_seqs)
            return

        req.decode_admit_time_ns = ready_time
        req.decode_capacity_queue_enter_time_ns = -1
        req.decode_capacity_queue_wait_ns = 0
        self.running.append(req)
        self._record_research_event(
            "DECODE_ELIGIBLE", ready_time,
            request_id=int(req.id),
            active_sequences=len(self.running),
            max_num_seqs=self.max_num_seqs)
        self.logger.info(
            "Decode handoff request #%d admitted at %d: active=%d capacity=%d",
            req.id, ready_time, len(self.running), self.max_num_seqs)

    def mark_batch_graph_start(self, batch, timestamp_ns):
        """Record the time a fixed scheduler batch is submitted for execution."""
        if int(getattr(batch, "execution_start_ns", -1)) >= 0:
            return
        timestamp_ns = int(timestamp_ns)
        batch.execution_start_ns = timestamp_ns
        if self.pd_type == "decode":
            if batch.requests:
                self.research_decode_phase_gate_open = True
            for req in batch.requests:
                if (req.decode_first_batch_id == int(batch.batch_id) and
                        req.decode_first_batch_start_ns < 0):
                    req.decode_first_batch_start_ns = timestamp_ns
        self._record_research_event(
            "BATCH_GRAPH_SUBMITTED", timestamp_ns,
            batch_id=int(batch.batch_id),
            request_ids=[int(req.id) for req in batch.requests],
            scheduler_role=str(self.pd_type),
            ranks=list(range(int(self.start_npu),
                             int(self.start_npu) + int(self.num_npus))))

    def _enqueue_decode_handoff(self, req):
        """Queue a KV-ready request by readiness time, behind preempted work."""
        index = 0
        while (index < len(self.waiting) and
               self.waiting[index].status == RequestStatus.PREEMPTED):
            index += 1
        key = (getattr(req, "decode_eligible_time_ns", -1), req.id)
        while index < len(self.waiting):
            queued = self.waiting[index]
            if queued.status == RequestStatus.PREEMPTED:
                index += 1
                continue
            queued_key = (getattr(queued, "decode_eligible_time_ns", -1),
                          queued.id)
            if queued_key > key:
                break
            index += 1
        self.waiting.insert(index, req)

    def is_request_empty(self):
        return (not self.waiting and not self.running and
                not self.inflight and not self.source_held)

    def print_result(self):
        # Extract ttft, tpot, and itl values from the completed requests
        ttft_values = [req.ttft for req in self.done]
        tpot_values = [req.tpot for req in self.done]
        itl_values = [itl for req in self.done for itl in req.itl]

        def _render(title: str, values, num_space=0):
            print_rule(f"[sim.tagline]{title}[/]")
            if not values:
                print_markup(f"No {title.split()[0]} data available")
                return
            mean = np.mean(values) / 1_000_000
            median = np.median(values) / 1_000_000
            p99 = np.percentile(values, 99) / 1_000_000
            label = title.split()[-1] if title != "Time to First Token" else "TTFT"
            # Map to the metric short-name used in the detail rows.
            short = {
                "Time to First Token": "TTFT",
                "Time per Output Token (excl. 1st token)": "TPOT",
                "Inter-token Latency": "ITL",
            }[title]
            spacing = " " * num_space
            print_markup(f"Mean {short} (ms){spacing}:                                                     {mean:.2f}")
            print_markup(f"Median {short} (ms){spacing}:                                                   {median:.2f}")
            print_markup(f"P99 {short} (ms){spacing}:                                                      {p99:.2f}")

        _render("Time to First Token", ttft_values)
        _render("Time per Output Token (excl. 1st token)", tpot_values)
        _render("Inter-token Latency", itl_values, num_space=1)

    # print each request results
    def print_request_result(self):
        # sort in id order
        self.done.sort(key=lambda x : x.id)
        for i in self.done:
            print(i)
        return

    # save requests information to an output file
    def save_output(self, output_file, is_append=False):
        if not os.path.isabs(output_file):
            output_file = f'../{output_file}'
        output_dir = os.path.dirname(output_file)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        mode = 'a' if is_append else 'w'
        with open(output_file, mode=mode, newline='') as file:
            # Initialize the CSV writer
            writer = csv.writer(file)
            
            # Write the column headers
            if not is_append:
                writer.writerow(['instance id', 'request id', 'model', 'input', 'output',
                                'arrival', 'end_time', 'latency', 
                                'queuing_delay', 'TTFT', 'TPOT', 'ITL',
                                'session_id', 'sub_request_index',
                                'npu_cache_hit_tokens',
                                'lower_tier_cache_hit_tokens',
                                'total_prefix_cache_hit_tokens',
                                'prefill_start_ns', 'first_token_visible_ns',
                                'p2d_kv_ready_time_ns', 'decode_admit_time_ns',
                                'decode_capacity_queue_enter_time_ns',
                                'decode_capacity_queue_wait_ns',
                                'decode_running_at_handoff',
                                'decode_max_num_seqs_at_handoff',
                                'decode_eligible_time_ns',
                                'decode_first_batch_id',
                                'decode_first_batch_decision_ns',
                                'decode_first_batch_start_ns',
                                'decode_first_batch_finish_ns',
                                'second_token_visible_ns', 'ttst_ns',
                                'paired_decode_instance_id',
                                'decode_phase_wait_ns'])
            
            # Write each request's information
            for req in self.done:
                writer.writerow([
                    req.instance_id,
                    req.id,
                    req.model,
                    req.input,
                    req.output - req.input,
                    req.arrival,
                    req.end_time,
                    req.latency,
                    req.queuing_delay,
                    req.ttft,
                    req.tpot,
                    req.itl,
                    req.session_id,
                    req.sub_request_index,
                    req.npu_cache_hit,
                    max(0, req.storage_cache_hit - req.npu_cache_hit),
                    req.prefix_cache_hit,
                    req.prefill_start_ns,
                    req.first_token_visible_ns,
                    req.p2d_kv_ready_time_ns,
                    req.decode_admit_time_ns,
                    req.decode_capacity_queue_enter_time_ns,
                    req.decode_capacity_queue_wait_ns,
                    req.decode_running_at_handoff,
                    req.decode_max_num_seqs_at_handoff,
                    req.decode_eligible_time_ns,
                    req.decode_first_batch_id,
                    req.decode_first_batch_decision_ns,
                    req.decode_first_batch_start_ns,
                    req.decode_first_batch_finish_ns,
                    req.second_token_visible_ns,
                    req.ttst_ns,
                    req.paired_decode_instance_id,
                    req.decode_phase_wait_ns,
                ])


def main():
    pass

if __name__ == "__main__":
    main()
