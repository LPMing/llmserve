# Candidate insights (maximum three)

Scoring is evidence quality, not perceived novelty. Each axis is 1–5. A candidate cannot advance merely by having an appealing name.

| Rank | Candidate | Evidence | Causal clarity | Cross-layer necessity | Natural occurrence | Network headroom | Serving headroom | Novelty | Realism | Decision |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | Dynamic communication exposure in the serving DAG | 4 | 4 | 3 | 2 | 4 | 2 | 2 | 3 | Best explanatory hypothesis; no paper PASS |
| 2 | Decode admission/iteration boundary shaping | 3 | 4 | 3 | 2 | 2 | 2 | 2 | 4 | Real discrete boundary effect, current maximum ~6.5% TTFT |
| 3 | Layerwise KV slack harvesting / release shaping | 3 | 3 | 3 | 3 | 3 | 2 | 2 | 2 | Progressive push helps TTFT modestly; packet/runtime release semantics are not validated |

## Candidate 1 — Dynamic communication exposure

Observation: shard and peer flow tails can be large while request handoff barely moves; controlled EP64 policy changes, in contrast, move collective CCT and TBT together. Natural Azure policy toggles are almost neutral.

Unified explanation: class membership is static, but criticality is a changing property of the serving dependency graph. A communication object is elastic while its extra network completion fits before the next barrier; it becomes inelastic as the barrier approaches.

System cause: request admission, batching, phase overlap, layerwise release, active Decode cohort and iteration cadence determine barrier and slack.

Network cause: sharing, priority, path and congestion control determine flow completion delta.

Why single-layer optimization may fail: flow-only laxity scheduling may not know when the dependency/barrier changes; system-only scheduling may not observe actual route/queue service cost.

Joint opportunity: expose per-object next-barrier slack to a network scheduler and let legal admission/release decisions alter the exposure window. No such joint gain has yet been measured.

Falsifiable prediction: for matched events, predicted exposed delay from remaining network work minus serving slack should correlate with integrated barrier/TBT delta; after conditioning on exposure, raw bytes/ECN/flow FCT should explain substantially less.

Smallest validation: one natural trace slice, same generated request/flow IDs and bytes, four cells (baseline, network-only oracle, system-only legal schedule, joint oracle), full integrated callback, per-object finish/barrier ledger; repeat on one independent window.

Novelty risk: high. “Prioritize low-laxity flows” overlaps directly with MFS/Nuska and coflow scheduling. The candidate is only distinguishable if system decisions change exposure and joint gain is non-separable.

## Candidate 2 — Decode iteration-boundary exposure

Observation: P2D-ready requests can arrive while a Decode group batch is in flight. A missed iteration adds a discrete wait; current natural-like 32D+32P2D case records 6.568ms (~6.5% TTFT), while adjacent 32D+64P2D records 1.418ms (~1.2%).

Unified explanation: network completion phase relative to a scheduler epoch, not only bytes, determines whether a request waits for the next batch.

System cause: batch barrier and iteration phase.

Network cause: completion time perturbation can move a ready event across the epoch boundary.

Joint opportunity: admission or P2D release could align completion with a legal batch boundary; network could protect transfers whose completion is near a boundary.

Falsifiable prediction: small controlled perturbations around naturally observed epoch phases cause a discontinuous admission-wait change; the same perturbation away from a boundary is hidden.

Smallest validation: replay the same real trace slice with scheduler-native event timing and a matched packet/network completion callback. Do not force arrivals; measure naturally occurring near-boundary events.

Novelty risk: batch/iteration scheduling and deadline-aware communication are established. Current observed serving effect is below the project threshold.

## Candidate 3 — Layerwise slack harvesting

Observation: layerwise P2D lets early shards drain behind later Prefill compute; POST_PREFILL increases network delay exposure, and progressive push reduced TTFT in exploratory tests (200G P99 -6.07%, TBT unchanged; larger gains only at lower link rates).

Unified explanation: release granularity changes how much communication work is hidden by compute, changing the barrier slack distribution.

System cause: layer production/release cadence and finite producer resources.

Network cause: service rate/backlog determines whether transfers drain before the final handoff.

Joint opportunity: shape release/concurrency of non-critical KV to preserve capacity for the final shard or EP barrier. Existing runtime transfer granularity and producer backpressure are not validated, so current oracle headroom is unknown.

Falsifiable prediction: at identical model bytes and compute profile, a legal transport/release mechanism changes critical KV/EP barrier and integrated TTFT/TBT at realistic link rates, without shifting cost to the other class.

Smallest validation: first audit actual NIXL/UCX chunk/WQE/release semantics; only then run matched integrated and packet cases.

Novelty risk: chunked KV and progressive transfer are known directions; simple progressive push is not enough.

## Ranking conclusion

Candidate 1 best unifies current evidence, but its current evidence establishes a useful measurement lens, not a validated optimization opportunity. No candidate currently satisfies >=20% network-critical and >=10% integrated serving improvement on a natural, repeatable workload. Do not present any as a confirmed CCF-A paper insight.

