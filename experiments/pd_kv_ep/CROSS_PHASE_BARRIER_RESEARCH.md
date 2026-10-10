# Cross-phase KV–EP barrier characterization

Date: 2026-10-08
Status: exploratory evidence is reproducible for the frozen window; no serving-level policy crossover established.

## Research question

Do model-derived layerwise P2D KV transfers and Decode-side MoE EP collectives interfere in ways that are amplified or hidden by their different completion barriers? In particular:

1. Are large and small KV transfers affected differently by the other KV flows and by EP traffic?
2. Are small KV requests more sensitive to EP than large KV requests?
3. Can EP queueing/ECN feedback on one KV flow affect later layer KV transfers?
4. Does a packet-network effect reach request handoff/TTFT or collective/TBT, rather than only changing an individual flow FCT?

The first-three questions are distinct. A single FULL-vs-isolated comparison estimates the aggregate externality of the other class; it does not by itself prove size-dependent KV-to-KV cross-interference.

## Current workload and physical setup

The authoritative replay is described in [`BARRIER_AWARE_BASELINE_FREEZE.md`](./BARRIER_AWARE_BASELINE_FREEZE.md). It uses a 16-request Azure 2024 window, Qwen3-30B-A3B-Instruct-2507, 48 layerwise KV releases, TP2, EP32, 8 servers in 1:1 P:D, four GPU ranks per 200-Gbps NIC, a 4-leaf/2-spine Clos with two parallel 200-Gbps links per leaf/spine pair, and 4-KiB packet payloads. P2D and EP bytes are model/routing-derived. The corrected q0 control / q1 policy-data / q3 ordinary-data priority semantics are active.

Matched controls preserve request event identity, issue schedule, source-port progression, physical path and directed-link set. Thus FULL-vs-isolated differences are packet-network counterfactuals under an identical offered schedule. They are not closed-loop serving counterfactuals.

## Finding 1 — request barrier hides most shard-level variation

Each request has 96 required KV shard flows (48 layers × TP2). Its request-level KV handoff is the maximum required shard finish relative to the first shard issue. It is not a sum of all flow latencies.

The 16 observed last shards are all from the final layer position; together they contain only 1.0417% of P2D bytes. The mean handoff span is 72.784 ms, while mean drain after the final layer release is 0.210 ms. Thus the 48-layer release cadence contributes about 72.574 ms before the last-release drain. A delay on an early shard is hidden whenever it remains inside the request's slack; it changes handoff only if it becomes the last required completion.

This supports the user's first mechanism as a **barrier/slack explanation** for the small request-FCT delta. It does not mean only the final layer experiences contention; it means only the last-completing required shard determines the request barrier. Under another path, workload or controller state, an earlier shard could become the straggler.

## Finding 2 — “large KV is less affected” is not established

There are 1,536 P2D shard flows, with empirical sizes from 18,432 B to 7,863,296 B. Under FAIR, FULL vs KV_ONLY gives:

| Shard-size cohort | n | Mean shard FCT, KV_ONLY → FULL | Paired relative change |
|---|---:|---:|---:|
| Smallest quartile | 384 | 68.782 → 68.834 µs | +0.065% |
| Largest quartile | 384 | 561.440 → 563.026 µs | +0.383% |

The larger shards show a slightly larger mean relative penalty here, opposite to the proposed “large transfers are inherently protected” direction, but both effects are small. Under EP_FIRST vs FAIR, the smallest/largest quartile means differ by only about +0.004%/+0.008%.

Important limitation: these are **layer/shard-size quartiles**, not bins of total KV bytes per request. A request-level size claim needs naturally occurring short-/long-context request cohorts. Also, the 16-request sample and one trace window are insufficient to generalize.

## Finding 3 — aggregate EP impact on KV barrier is tiny in this window

Matched FULL/FAIR vs KV_ONLY:

- Mean shard FCT: 284.876 vs 284.302 µs (+0.574 µs, +0.176%).
- Request handoff mean: 72.783929 vs 72.780413 ms (+3.516 µs).
- Request handoff absolute P99: 117.342448 vs 117.336869 ms (+5.579 µs, +0.00475%).
- Paired request handoff ratio P99: +0.0314%; this is a percentile of 16 per-request ratios, not the ratio of the two marginal P99s.

This is consistent with the large inter-layer release span and barrier slack masking most per-flow perturbations. It is not proof that P2D and EP use disjoint links: their routed flows overlap, and the matched controls preserve exact packet-derived path/link sets.

## Finding 4 — small KV is not shown to be more EP-sensitive

The current measurements do not support this hypothesis. In the shard bins, the smallest quartile has less FULL-vs-KV_ONLY FCT increase than the largest. At request barrier level, the effect of adding EP is tiny for all 16 requests. A stronger test should:

1. Use natural request-total KV size (input length × model KV geometry), not shard quartiles.
2. Keep a target request's arrival, flow sizes, release times, endpoints and route fixed.
3. Compare its completion with the other-size cohort present vs absent, while holding other background events fixed; preserve source-port progression so ECMP path identity does not change.
4. Repeat in more than one naturally occurring trace window and report target-flow FCT **and** request last-shard handoff.

Only then can we distinguish “small KV is more queue-sensitive” from “small KV is less critical because it has more barrier slack.”

## Finding 5 — EP barrier is highly priority-sensitive, but not automatically a new crossover

Across 5,280 packet-level collectives:

| Policy | EP CCT mean / P99 | Absolute P99 vs EP_ONLY |
|---|---:|---:|
| EP_ONLY | 38.061 / 66.375 µs | baseline |
| FULL / FAIR | 38.461 / 66.724 µs | +0.525% |
| FULL / EP_FIRST | 38.067 / 66.379 µs | +0.006% |
| FULL / KV_FIRST | 71.339 / 635.865 µs | 9.58× |

Under this fixed issue schedule, KV_FIRST produces a severe EP tail; EP_FIRST nearly recovers EP_ONLY. Conversely, EP_FIRST vs FAIR changes request KV handoff negligibly in this window. This is a directional risk result, not evidence that there is no cost to EP_FIRST in all workloads. It also does not support a policy crossover: this window favors protecting EP, and lacks a demonstrated serving-visible KV penalty for that choice.

For FAIR, collective-level per-paired ratios have a long tail (P99 1.390) even though the ratio of the two marginal absolute P99s is only 1.005. Those are different statistics. Sparse paired outliers should not be reported as a general 39% P99 slowdown without showing their identities and denominator.

## ECN: why many marks, and what they do (and do not) prove

The replay sends billions of model-derived bytes as 4-KiB payload packets over finite 200-Gbps links. Across 64 physical scale-out directed links, FULL/FAIR has 257,649 ECN-marked link-TX observations out of 10,258,104; the observed ratio is 2.51%. A packet may be counted at each traversed link. The queue crosses Kmin during persistent concurrent traffic, so marking is plausible even though the maximum observed queue (4.48 MiB) is below the 32-MiB shared buffer. EP_ONLY has no marks because its short/bursty queues remain below the configured marking region in this trace; it still reaches a sampled utilization of 1.0. ECN count is therefore not a utilization meter.

Crucially, this matched replay's `CC_MODE=12` has no matching CNP rate-control handler in the current backend. These ECN values prove that marking telemetry is active; they do **not** prove a DCQCN sender slowed down in these runs. The repository has a separate `CC_MODE=1` study that verified ECN→CNP→DCQCN rate decrease/recovery and observed large per-flow FCT changes but <1% KV request-barrier change in the tested long-KV cases; see [`PACKET_LEVEL_AUTONOMOUS_RESEARCH.md`](./PACKET_LEVEL_AUTONOMOUS_RESEARCH.md). The same Azure16 issue ledger has now also been rerun under `CC_MODE=1`; its paired result is in [`DCQCN_MODE1_MATCHED_REPLAY_REPORT.md`](./DCQCN_MODE1_MATCHED_REPLAY_REPORT.md). Across these runs, cross-request QP-state inheritance remains unsupported: this replay wrapper creates a new source port/QP per `send_flow`, and completion deletes it.

Do not optimize “ECN count” in isolation. Raising thresholds may hide marks while allowing deeper queues or PFC; limiting rate may reduce marks but worsen KV completion. The objective must be barrier/serving latency under a validated congestion controller, with queue, CNP, QP rate and recovery telemetry as mechanism evidence.

## What could become a paper motivation — and novelty boundary

The strongest **evidence-backed** mechanism here is the mismatch between flow-level congestion and request-level exposure: many KV shards can be delayed without moving the request barrier because the layerwise release span creates slack, while a few EP peer stragglers can dominate a collective barrier. However, “schedule stage-aware KV and collective communication according to criticality/slack” is already very close to the publicly available work **Nuska (initially titled Multi-stage Flow Scheduling / MFS)**. Its paper explicitly studies reusable KV retrieval, prefill collectives, P2D KV, layerwise communication, inter/intra-request contention and urgency-aware flow promotion for TTFT. A generic cross-phase priority/criticality scheduler is therefore not a safe novelty claim. See [Nuska / MFS, arXiv v2](https://arxiv.org/html/2603.17456).

Related foundations also matter: [DistServe (OSDI 2024)](https://www.usenix.org/conference/osdi24/presentation/zhong-yinmin) establishes P/D disaggregation and SLO-aware resource/placement decisions; [Mooncake (FAST 2025)](https://www.usenix.org/conference/fast25/presentation/qin) develops a KVCache-centric disaggregated serving architecture; and [DCQCN (SIGCOMM 2015)](https://conferences.sigcomm.org/sigcomm/2015/pdf/papers/p523.pdf) already establishes ECN/CNP-based RDMA congestion control. The potentially differentiating angle would have to be a **packet-level, recurrent Decode-EP collective-barrier interaction with cross-request P2D**, including validated QP feedback and serving exposure—not the basic fact that KV and EP share a fabric, nor generic priority scheduling.

Candidate questions worth testing, not claiming as discoveries:

1. **Request-size-conditioned KV cross-interference:** do natural large P2D requests create a measurable tail penalty for concurrent small requests, and does the victim depend on which shard is barrier-critical? This differs from the currently tested aggregate EP-to-KV effect.
2. **Feedback memory across transfer phases:** does validated DCQCN state persist long enough on a reused QP to hurt a later layer/request after the triggering EP burst has ended? This requires a real QP-lifecycle audit first.
3. **Collective-period aliasing:** do ECN/CNP feedback and recovery windows repeatedly land on later Decode EP rounds, causing recurrent barrier stalls? Current CC_MODE invalidates any such claim; first establish controller correctness.
4. **Slack versus congestion observability:** can a flow's ECN/FCT tail predict whether it will become the request's last shard, or does layerwise release slack make common network alarms poor predictors of TTFT exposure? The current window suggests a large gap, but more traces are required.

None is yet CCF-A/B-ready. The current results are a useful negative/diagnostic baseline: FAIR adds little average/P99 barrier cost in this Azure window; static KV_FIRST can severely hurt EP; EP_FIRST is nearly free for the measured KV barrier here. No fixed-policy crossover or packet-derived TTFT/TBT result has been established.

## Next evidence-producing steps

1. **Keep CC modes separated:** mode-1 DCQCN feedback correctness already passed in the separate packet study. If testing ECN feedback against this exact Azure16 workload, generate new matched `CC_MODE=1` and `CC_MODE=0` runs; preserve the frozen mode-12 artifacts and report them as static-priority/marking results only.
2. **Test size effects directly:** select natural small/large request-total-KV cohorts from another Azure/BurstGPT window; use matched target requests and controlled presence/absence of the other cohort. Keep generated model bytes, timing, route identity and physical 200-Gbps links intact.
3. **Test cross-request QP state only if runtime evidence supports reuse.** If the actual transport opens fresh QPs, drop the state-inheritance hypothesis rather than inventing persistence.
4. **Only after a robust packet barrier effect**, integrate packet completion feedback into a small serving case to obtain valid TTFT/TBT. The current fixed-time replay cannot supply these metrics.
