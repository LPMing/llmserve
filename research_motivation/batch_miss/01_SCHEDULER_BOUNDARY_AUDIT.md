# Scheduler boundary audit

## Scope and baseline status

This audit is against the current local, dirty checkout at `0c0839aff54ec0abb1810dc09cf3d66f06b1b078`, with the working-tree changes preserved. The relevant run path is full serving-integrated FlowSim. The audited configuration is TP1/EP4, PP1, `max_num_seqs=8`, `max_num_batched_tokens=2048`; it does not claim strict GateRouter A2A (the current simulator emits its profiled AG/RS collective representation).

Relevant code: `serving/core/scheduler.py::schedule`, `_schedule_running`, `_schedule_waiting`, `_build_batch`, `_schedule_existing`, `add_decode`, `mark_batch_graph_start`; `serving/core/router.py::transfer_prefill_request`; `serving/__main__.py` FlowSim completion loop; `serving/core/flowsim_worker.py` graph/network completion callbacks.

## Actual state transitions

1. P2D data flows are released by the Prefill graph, while Prefill compute continues. The receiving Decode scheduler is notified only after the Prefill graph and its required communication dependencies complete. In the measured request, the last KV flow finishes at 127.654649ms, but the Prefill sampler/graph finishes at 128.817ms. Therefore `t_ready = max(t_prefill_finish, t_last_required_KV_finish) = 128.817ms` for this path.
2. `add_decode(req, completion_time_ns)` records `P2D_READY`; it checks `len(running) >= max_num_seqs`, and otherwise appends the request to `running` and emits `DECODE_ELIGIBLE`. When capacity is full it queues the request and emits `DECODE_CAPACITY_WAIT`.
3. `schedule()` at the start rank first tries to join an existing batch, then checks the PP in-flight cap. With PP1, an already-built/executing batch has immutable membership; an arriving request cannot be added retroactively. After graph completion/wakeup, a new `_build_batch()` is the next selection point.
4. `_build_batch()` records the batch membership and the first Decode batch ID/time on the request. FlowSim's graph `submit` and `graph_completed` events independently identify execution start and end.

## Measured target boundary (E3, request 24)

| Event | KV-isolated | FAIR shared |
|---|---:|---:|
| P2D-ready / Decode handoff | 128.817000ms | 128.817000ms |
| Existing R0 batch 8 completes | 130.073992ms | 130.228511ms |
| Batch 9 selected / graph submitted | 130.073992ms | 130.228511ms |
| R1 selected batch | 9 | 9 |
| R1 Decode active count at handoff | 6/8 | 6/8 |
| Active count after admission | 7/8 | 7/8 |
| Capacity wait | 0 | 0 |
| Free KV blocks at handoff | 47,623 / 47,806 | 47,623 / 47,806 |
| Batch token budget used | 7 / 2,048 | 7 / 2,048 |

The request is ready 1.256992ms before the isolated Batch-9 selection and 1.411511ms before the shared-run selection. It is eligible before selection, has a sequence slot and ample KV blocks, and is actually selected into Batch 9. No Batch-8 admission is possible because Batch 8 membership was already fixed. The experiment thus observes the real batch boundary but does **not** observe a network-induced crossing of it.

There are 24 seed requests: six per each of four paired P/D lanes; each receiving scheduler has eight sequence slots. Four candidate requests are assigned one per lane, taking each lane from 6/8 to 7/8. These are sequence-slot counts, not GPU-utilization claims. In particular, the four Decode ranks participate in one EP4 group; they are not four independent EP collectives.

## Gate result

The discrete batch-selection boundary exists and completion wakeups are exercised. The first failure in the proposed causal chain is earlier: shared-network contention did not delay `P2D_READY` at all. Accordingly, `BATCH_MISS_NOT_OBSERVED`; no phase-scan probability is inferred from this single controlled phase.
