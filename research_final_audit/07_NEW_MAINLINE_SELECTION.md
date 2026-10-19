# 07 — New-mainline selection after KV/EP priority NO-GO

## Selected bounded candidate

**Sparse MoE A2A traffic geometry and collective-tail exposure** is selected
only as the next *question to test*, not as a validated paper mainline.

The question is whether, with legal token-to-expert work and model-derived
traffic held fixed, a real sparse all-to-all peer matrix creates a small set of
route/cut stragglers that determine a Decode collective barrier—and whether
sharing with P2D changes that exposure beyond the generic EP route-geometry
effect.

## Why this candidate, and what it is not

It is adjacent to observed EP CCT variability and asks a mechanism question
that the old KV-vs-EP class-priority results did not isolate. It is not a claim
that route-aware placement is new: FAST (NSDI'26), SwiftEP (NSDI'26), ELDR and
MoE incast/placement work are strong prior art. A contribution would require a
serving-specific collective-barrier effect and a real control opportunity that
those systems do not already provide.

Do not proceed to a routing algorithm, placement algorithm, priority policy,
or paper prototype based on the current first screen. It is classified
`SPARSE_A2A_MODEL_NOT_VALIDATED`; the generated route counterfactual is not a
semantically matched alternative and the events are not per-layer integrated
collectives.

## One bounded next action if the project is explicitly resumed

Repair or replace the minimal event builder so each event is tied to actual
token→expert assignments from a named legal routing trace (or a clearly
bounded, work-preserving routing seed), and emit separate dispatch/combine
barriers for each Decode round/layer. Then run one FlowSim EP_ONLY/FULL matched
pair against a valid route realization and one negative non-shared-cut control.
Only if P2D materially changes the barrier result should integrated serving or
packet validation be considered. Do not expand request count or load to
compensate for invalid semantics.

This action is a validation prerequisite, not authorization to claim a paper
result. If a valid matched route cannot be constructed without changing model
work, close this candidate as not testable in the current simulator.

