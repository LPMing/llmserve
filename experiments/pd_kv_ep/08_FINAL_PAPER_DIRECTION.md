# Final paper direction after historical evidence reconstruction

## Current decision

Status: JOINT_PD_MOE_SCHEDULING_NOT_VALIDATED.

The bounded generic KV×EP shared-fabric line has a final negative result for the tested legal FlowSim setup; historical controlled cases show mechanisms can exist. The broader joint system+network direction is not yet a PASS or a universal NO-GO because the required same-natural-workload four-cell oracle is absent and natural exposure scanning has not been completed across all retained trace families.

Do not currently pitch a CCF-A-ready optimization or claim >=20% network plus >=10% serving headroom.

## Problem

Provisional problem statement: PD-disaggregated MoE serving creates communication delays at multiple barriers, but raw network congestion is a poor proxy for serving impact because Prefill release slack, Decode iteration work and batch epochs selectively hide or expose those delays.

This is an observation/problem-definition candidate, not yet a validated system problem.

## Key observation

Evidence-backed examples:
- KV shard P99 can increase by ~2x to 8x while request handoff moves <0.05%.
- A controlled EP64 FAIR→EP_FIRST comparison moves EP CCT P99 -50.54% and integrated TBT P99 -21.72%.
- Two natural Azure EP64 windows show near-zero FAIR→EP_FIRST effect.
- At a minimal shared-ToR D16+K8 point, common-link overlap exists but EP CCT P99 rises 5.11% and TBT P99 0.47%.
- The 512-request fan-in network-only effect does not have an integrated serving counterpart.

Together these motivate an exposure lens; they do not prove a solution.

## Insight

Provisional: Criticality is a time-varying property of the serving dependency graph, not a permanent property of KV or EP traffic class. System state sets the remaining slack and next barrier; network service sets the communication completion perturbation.

## Why network-only may fail

Class-priority policies optimize traffic classes even when most delayed communication is hidden behind layerwise compute or not on the request/token critical path. Natural Azure policies were nearly identical.

## Why system-only may fail

A system scheduler that shifts/admission-schedules work without observing actual link/path service, queue and completion may create an intended overlap change but miss the bottleneck. This is a hypothesis; the current experiment set has no clean system-only oracle on the same natural bytes.

## Why joint optimization is not yet shown necessary

No same-workload matched baseline/network-only/system-only/joint factorial exists. Existing “network-only” and “system-only” results are from different workloads or backends, so synergy cannot be calculated. We have no evidence that joint gain beats both single-layer gains.

## Proposed abstraction if validation succeeds

Per communication object, estimate:
- remaining serving slack to its next request, collective, token, or admission barrier;
- remaining network service time;
- whether completion gates progress;
- confidence/error bound of those estimates.

A positive slack deficit means the object is predicted to miss its next barrier. A controller could then combine legal system-side phase/admission shaping with barrier-exposed network service. This is a validation target, not an implemented design.

## Design sketch (not implemented)

1. Serving event export: attach request/token/collective identity and next-barrier dependency to communication releases.
2. Exposure estimator: update remaining slack and network completion estimate using observed progress.
3. Joint oracle first, then deployable controller only if same-trace factorial shows non-separable benefit.

No scheduler, routing, priority or transport mechanism is implemented by this report.

## Evidence and gates

Current strongest positive mechanism: controlled EP64 TBT P99 -21.72%.
Current natural matched evidence: two Azure windows with effects below 0.3%.
Current minimal legal shared-fabric gate: D16+K8 yields <10% network and <10% serving changes.
No natural matched joint window with >=20% network-critical opportunity and >=10% serving improvement has been demonstrated.
Replication across workload families is incomplete.

Required before a paper claim:
- a naturally occurring, exposure-selected window with >=20% network-critical headroom;
- >=10% integrated TTFT/TBT/TPOT gain;
- identical bytes/compute/request set across four oracle cells;
- second independent trace/window or seed;
- confidence intervals and admission/goodput/SLO accounting;
- a packet-level representative validation if the claimed mechanism depends on queue/CC/QP behavior;
- novelty proof against stage-aware laxity scheduling and system-side partitioning/scheduling.

## Target venue and risk

If the effect becomes a genuine network/runtime coordination problem with packet-level evidence and strong serving/SLO gains, NSDI/SIGCOMM/EuroSys could be considered. If the contribution remains a simulator-supported serving scheduling result, target and claim should be adjusted accordingly. Venue is not presently supportable.

Largest review risks: (1) overlap with Nuska/MFS; (2) only controlled synchronization creates the effect; (3) network-only gain is absorbed by compute; (4) FlowSim fluid results are mistaken for packet effects; (5) non-paired percentiles are used as causal evidence; (6) no exact joint-synergy experiment.

