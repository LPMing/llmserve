# Communication exposure model

## Hypothesis

A network slowdown becomes serving-visible only when it delays a dependency that gates progress after available overlap/slack is consumed. This is a tested hypothesis, not an axiom.

## Objects, events, and slack

For a communication object c (KV shard/chunk, EP peer message, EP collective), record:
- release(c): the system makes the transfer eligible;
- finish(c): network completion;
- B(c): next serving barrier that cannot advance without c;
- F0(c): matched-baseline finish;
- delta_net(c): counterfactual finish perturbation.

For a fixed max barrier, B0=max_i F0(i). Then slack(c)=B0-F0(c), and if only c changes while all other dependencies stay fixed:

exposed_barrier_delta(c)=max(0, delta_net(c)-slack(c)).

This follows from the max-completion rule. It explains early-shard masking and why shard FCTs are not summed into request handoff.

For an EP collective the barrier is the last required peer. To affect a Decode token, the CCT perturbation must additionally survive compute overlap and the scheduler's iteration/batch boundary. For TTFT, P2D-ready must gate Decode admission/first token. P2D transfers may overlap Prefill computation and must not be added twice to arrival-to-Prefill time.

## Measurable quantities

For paired runs with a valid object/barrier match:
- Network perturbation: delta_net = finish_counterfactual - finish_baseline.
- Barrier perturbation: delta_barrier = barrier_counterfactual - barrier_baseline.
- Exposure ratio: delta_barrier/delta_net, only when delta_net is nonzero and pairing is valid.
- Serving exposure: delta_serving/delta_net, only from integrated matched runs with same requests, bytes, compute and topology.
- Object slack: baseline barrier time minus that object's baseline finish.
- Request P2D slack: relation of last required shard finish to Prefill completion and Decode admission.
- EP slack: collective completion relative to iteration completion/next token boundary.

Ratios may be negative, near zero, near one, or greater than one. Negative values can occur when other schedule events shift. Values above one can occur if a small delay crosses a discrete scheduler epoch. Missing or incomparable values are NA, never zero.

The exported natural request breakdown separates arrival→Prefill completion, Prefill completion→P2D-ready, P2D-ready→Decode admission and admission→first token; these segments close to TTFT on retained rows. P2D flow work overlaps the first segment, avoiding double counting.

## Exposure-window predicate

A first-order exposure candidate requires all of:
1. network activity overlaps in time and on a modeled shared resource;
2. the delayed communication is critical or can become critical: last required KV shard, last EP peer, or a near-last object;
3. predicted extra network completion exceeds remaining slack to its next serving barrier;
4. that barrier lies on TTFT/TBT/TPOT path and is not hidden by compute, batch or admission delay.

High load, ECN or overlap alone is not an exposure window.

## What determines exposure

The current serving scheduler selects request admission, active Decode
population, batch membership, Prefill/Decode overlap, and iteration cadence;
these alter active-set geometry and serving slack. P2D release granularity is
currently a run-level mode (`LAYERWISE`/`POST_PREFILL`), not an online serving
decision. The current network policy changes service order and bandwidth share
among active flows. Paths are selected by the configured routing model (for the
audited FlowSim runs, deterministic shortest-path BFS over directed aggregate
links), not by the network scheduler. Active-flow concurrency follows from
release/dependency events and the chosen paths.

A joint controller might need both. Current evidence does not show that joint control beats both single-layer controls on identical natural input.

## Historical evidence check

- KV self-contention/DCQCN: shard tails rise ~2x or 5–8x while request handoff changes <0.05%.
- Final-shard residual drain: +23.568% while request handoff +0.0115%; final shard completes before Prefill completion.
- Controlled EP64: EP CCT P99 -50.54% under EP_FIRST and TBT P99 -21.72%.
- Natural Azure EP64: matched policy changes are near zero; final KV completion is before Prefill completion; measured admission wait is <10% of TTFT.
- POST_PREFILL: removing layerwise release slack increases drain visibility and TTFT modestly, below serving gate.
- Decode batch boundary: a naturally timed ready request misses an in-flight batch and adds 6.568ms (~6.5% TTFT); adjacent point is ~1.2%.
- Minimal shared ToR: actual common-link overlap but queue episodes are short; strongest point gives +5.11% EP CCT P99 and +0.47% TBT P99.
- High-concurrency FlowSim and packet results have larger flow/barrier changes, but no same-run integrated completion feedback.
- Azure Code n44 targeted capture verifies natural same-directed-resource sharing in FlowSim, but the fully coactive 463–466ms collectives do not show a higher observed CCT than controls; KV still completes 1.271ms before Prefill completion. Without a matched counterfactual and exact per-object barrier slack, this is a sharing observation, not positive exposed delay.

## Limits and falsification

This model is explanatory, not predictive. Most historical data lacks per-object baseline finish, exact next barrier, and matched delta for every object. System events can move when completion changes, invalidating static slack subtraction. Native packet replay has fixed issue times and no scheduler callback. FlowSim has no packet queue or CC.

A falsification-grade experiment must log per transfer/token: release, finish, next barrier, remaining compute, batch epoch, request/token identity; then compare predicted exposure with observed integrated TTFT/TBT under matched counterfactuals.

## Implementation-grounded serving/network coupling (2026-10-10 audit)

The integrated FlowSim path is event-coupled, but the current serving policy is
not exposure-aware:

- `Scheduler.schedule()` in `serving/core/scheduler.py` serves its persistent
  `running` set first, then admits from the arrival-ordered `waiting` queue
  while token/sequence budgets permit (`_schedule_running()` and
  `_schedule_waiting()`). It does not inspect network slack or link state.
- In `LAYERWISE` Prefill, `_emit_sequence()` attaches model-derived KV bytes to
  each `qkv_proj` layer (`serving/core/trace_generator.py`). MoE routing is
  generated from the configured GateRouter and active source-token vector in
  `_emit_moe_block()`; A2A_P2P emits the nonzero source/owner peer matrix.
- `flowsim_worker.py::advance()` selects the next local-compute or network
  event. `_finish_node()` releases dependent DAG nodes only after all parents
  finish; `_complete_flow()` records completion. Thus changing network service
  can move subsequent local/collective events in this integrated backend.
- Once the Prefill/P2D barrier completes, `router.transfer_prefill_request()`
  stamps `p2d_kv_ready_time_ns` and calls Decode `add_decode()`. Decode then
  enters its normal waiting/running queues; the next group iteration is
  recorded at scheduler issue and completion. These timestamps, not an
  offline flow-FCT sum, define the serving-visible path.
- `FlowSpec` records bytes, release, class and provenance. `_waterfill()` / 
  `_rates()` allocate fluid max-min (or configured class policy) over directed
  paths; the model does not represent packet queues, ECN/PFC, transport
  feedback, or a finite producer/NIC injection window. Reported backlog is
  analytical residual fluid only.

Consequently, the existing frontend/backend already couples network completion
to serving progression, but has no system action that deliberately changes
which ready request/communication becomes exposed. The 2x2 necessity test must
therefore implement offline characterization controls at well-defined seams,
preserve legal dependencies, and validate realized bytes/routing after every
cell. A static fixed-release network replay cannot serve as `SYSTEM_ONLY`.
