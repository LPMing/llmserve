# 05 — Baselines and novelty audit

## Baselines actually supported by evidence

| Baseline/policy | Scope represented | Evidence status |
|---|---|---|
| FAIR / max-min | FlowSim controlled and selected natural prefixes; one corrected minimal shared-ToR gate | Measured on named fixtures; not a universal hardware scheduler. |
| EP_FIRST / KV_FIRST | Controlled class-priority experiments, including a strong EP64 point and smaller shared-NIC fixtures | Measured in those fixtures. EP_FIRST is already a strong incumbent; no robust natural TTFT penalty was found. |
| Request-first Decode opportunity | One bounded integrated controlled case and neighboring output-length case | A narrow request-level opportunity, not a general scheduler and not a P99/SLO result. |
| SJF/SRPT, EDF, LLF | No final matched run on frozen natural windows | NOT_RUN. Do not claim they were beaten. |
| Coflow/collective-aware scheduler | No final matched natural-window oracle | NOT_RUN. Historical equal-size FIFO/coflow sensitivity is not an implementation or an adequate universal baseline. |
| Full Nuska/MFS | No code-level reproduction or matched comparison | NOT_RUN. The old priority idea cannot be presented as novel merely because the workload includes Decode EP. |
| Offline barrier-aware oracle | No final global oracle with collateral accounting | NOT_RUN. The narrow Decode-opportunity diagnostic is not this oracle. |

## Novelty finding for KV/EP flow priority

The proposed contribution “give KV and EP flows different priorities” overlaps
directly with stage-aware, inter-request communication scheduling. Nuska is the
v2 title for the MFS preprint lineage, not a separate second prior work. Its
stated scope includes multi-stage disaggregated serving, inter-/intra-request
contention, laxity-based scheduling, defer/promote and multi-level queues to
improve TTFT SLO. The present project did not reproduce the complete method, so
it cannot make a superiority claim against it.

The experiments also weaken the distinct technical motivation: a controlled
static EP_FIRST policy already captures the large measured Decode protection
point, while natural windows show little TTFT/TBT movement and KV handoff slack.
No verified same-class/request/collective arbitration opportunity remains that
is both sizeable and unhandled by known deadline/coflow/stage-aware methods.

## Novelty finding for sparse A2A geometry

“MoE collective route geometry changes CCT” is not novel by itself. FAST
(NSDI'26) directly studies skewed All-to-All-v collective communication,
including incast/straggler behavior and collective completion. SwiftEP
(NSDI'26) is also a strong MoE inference All-to-All execution incumbent.
ELDR, expert-placement work and rate-based MoE incast scheduling further narrow
the room for a generic locality/skew claim.

A potentially distinct paper would need all of the following, none of which is
validated by this audit:

1. actual per-layer, per-Decode-round sparse routing semantics rather than a
   48-layer-coalesced event;
2. a legal matched route/placement or scheduler intervention that preserves
   token-to-expert work, request timing and communication bytes;
3. an effect that appears or is materially amplified when P2D shares the fabric,
   not an EP_ONLY geometry gap;
4. integrated completion feedback showing a stable TTFT/TBT/barrier benefit;
5. a technical distinction from FAST/SwiftEP and stage-aware serving scheduling.

Until those gates pass, do not label “Sparse A2A Traffic Geometry and
Collective-Tail Exposure” a validated paper direction. It remains a bounded
research candidate with a failed/invalid first screen.

