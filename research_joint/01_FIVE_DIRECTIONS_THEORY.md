# Five-direction theory gate

This is a bounded selection screen, not a claim that every imaginable joint controller has been disproved. No large trace was run.

## Shared arithmetic

For Qwen3-30B-A3B BF16, full KV per input token is `48 layers × K/V × 4 KV heads × 128 head_dim × 2 B = 98,304 B/token`. At 2,048 input tokens: `201,326,592 B = 192 MiB`; TP2 produces two required `100,663,296 B = 96 MiB` shards. At a single 200-Gbps/25-GB/s cut, a shard's ideal serialization is 4.02653184 ms, and a full request shard-pair is **not** attributed to a cut that carries only one shard. These are cut work bounds, not observed P2D-ready times.

For a placement candidate `d`, the simplest critical-path lower bound is `start(d) ≥ max(KV_ready(d), Decode_available(d))`; actual admission can be later due to capacity, batch epochs, memory, and group barriers. A network-only selector minimizes `KV_ready`, a compute/load-only selector minimizes `Decode_available`, and the joint selector minimizes the maximum plus scheduler constraints. This is a standard joint cost, not itself a novel algorithm.

For EP, each collective's completion is `max_i(flow_finish_i)`. Directed-cut work `W_l/C_l` is a lower bound only when the counted bytes actually traverse that cut and compete for its capacity. Per-token exposure requires summing only the collectives on the true critical Decode iteration and accounting for overlapped compute. It is invalid to convert network CCT directly into TBT without that path.

## Direction A — network-aware P/D placement and admission

The motivating shape requires at least three fixed-resource Decode choices with different pairs `(network-ready, compute-available)`, such that the decision from `argmin KV_ready` or `argmin Decode_available` differs from `argmin max(KV_ready, Decode_available)`, and that difference survives queue/group constraints into first/second token or completion. A three-row theoretical witness can show the math, but only measured candidate readiness can validate it.

The current archive already contains a two-lane controlled slot-crossing: a selected target's second token moved 3.381 ms earlier, but the pair makespan changed only 43.5 µs (~0.014%); with a neighboring Decode seed, the effect shrank to ~43 µs. A matched multi-placement study changed EP CCT only 0–7.1% in tested trace windows. Thus a local request-level opportunity exists, while aggregate serving headroom is small and unstable. NetKV directly selects Decode instances using network cost together with load/cache eligibility; this is a prior-art blocker for the simple A control law. A new three-candidate serving sweep is not justified until a specific non-covered state variable and target objective are identified.

**Gate:** theoretical mechanism possible; demonstrated incremental headroom beyond network-aware decode routing is not. No new A run. `A_PLACEMENT_NO_INCREMENTAL_HEADROOM` for this paper candidate, not a universal physical impossibility.

## Direction B — phase staggering independent EP groups

Two independent barriers can contend on a common 200-Gbps directed cut. A one-time initial phase shift may remove recurrent phase overlap if the offset exceeds the actual collective windows and if later releases do not reconverge. A conservative homogeneous ceiling for an old EP64 equal-shape profile was 519.045 µs per token over all 48 layers and dispatch+combine, against an estimated 16.899-ms token interval (~3.07%); this assumes every phase aligns and all relevant cut work is removed. It is an optimistic same-shape ceiling, not a serving prediction. In the exercised EP4 group workload, the measurable per-round CCT delta was smaller: dispatch 0.696 µs and combine 0.328 µs, hence 49.152 µs over 48 layers per token (~0.80% of a 6.1084-ms interval).

An offset can help only if its one-time first-token-to-Decode hold cost is amortized by recurrent reductions, both groups' performance is counted, and the long-run collective phases remain separated. The 20-µs test directly checks that condition in one 32-output controlled run. It did; however the serving gain was below 1%, TTFT did not change because Prefill produced the first token, and the experiment used AG/RS rather than sparse A2A. Generic collective coordination is also established prior art (Symphony/Harmonics). No larger EP experiment is warranted under this result.

**Gate:** `THEORY_SIM_CONSISTENT_POSITIVE` for phase overlap removal; **paper-motivation/novelty gate FAIL** due <1% serving headroom, controlled synchronized arrivals, AG/RS semantics, and direct prior art.

## Direction C — batch composition × A2A cut geometry

Raw payload for one token's top-8 hidden vectors is `8 × 2,048 × 2 = 32,768 B`; 64 tokens yield 2 MiB before any local-expert elimination, routing aggregation, or implementation-specific dispatch/combine accounting. This is a scale check only. The current `GateRouter` BALANCED path is a closed-form per-rank work approximation and does not retain a provenance-backed token→expert-owner matrix for legal batch reorder comparisons. The integrated collective tested in B is AG/RS. Therefore current code cannot compare same-token-set, same-compute, exact sparse A2A cut work without adding an actual routing trace/API and proving equivalent batch semantics.

Existing FAST (A2A schedule), Semantic Parallelism (model/data co-scheduling and inter-request rebatching), and Gimbal (cross-level/source-aware MoE scheduling) create a high overlap burden. Without an exact legal route matrix and a distinct cut-level policy not covered there, a new C simulation would be synthetic or redundant.

**Gate:** `C_NO_TRAFFIC_GEOMETRY_HEADROOM` for this simulator evidence path; no simulation. This means not representable with the currently retained exact source data, not that all MoE batches have identical routes.

## D/E — bounded theoretical exclusions

- **D: generic class/flow/request priority.** Earlier controlled experiments show priority can move network CCT substantially but endpoint barriers often absorb it, and EP_FIRST already recovers the demonstrated EP-side case. Request/deadline/stage-aware priority overlaps Nuska/MFS and conventional EDF/LLF/coflow. No independent new control hypothesis remains in this mission; do not relabel priority as joint optimization.
- **E: Progressive Push / early KV release.** The repository has a separate semantic audit and opt-in implementation. It is deliberately out of scope here and the user explicitly prohibits reimplementing it. It changes transfer architecture, not the A/B/C control being screened.

The machine-readable decisions are in `02_THEORY_GATE_RESULTS.csv`. A no-go is limited to these tested/represented envelopes, not a theorem over every model, topology, or SLO.
