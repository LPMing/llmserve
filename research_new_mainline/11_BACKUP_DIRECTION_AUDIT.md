# Backup directions: theory-only screen

No backup network/serving experiment was run because the primary owner-readiness direction did not pass its theory gate and the required current-version sparse owner DAG is unavailable. This section screens whether the named backups justify reopening now.

## Backup P1 — Critical peer route and task ordering

- Potential mechanism: an owner whose result is last on a required token path may have a different directed route/cut from the median peers; service ordering could shorten the collective tail.
- Existing closest work: FAST (NSDI 2026) schedules all-to-all network work under dynamic traffic; coflow/collective scheduling and critical-flow policies are also direct baselines. A simple “prioritize the last peer” is not enough because service changes can migrate the straggler.
- Current evidence: historical `CRITICAL_EP_PROTECTION_VALIDATION.md` is a negative/cautionary offline critical-flow result; historical group-urgency bound is AG/RS and not owner route data. No current exact Qwen Decode pair matrix plus physical paths is joined to a calibrated owner compute DAG.
- Decision: `NOT_READY_FOR_THEORY_BOUND`; no FlowSim run. Reopen only with actual route matrix, mapped paths, exact token-required peer sets, and matching profile.

## Backup P2 — Collective startup exposure

- Potential mechanism: fixed dispatch/combine startup can repeat across 48 layers and become exposed at the Decode token barrier.
- Limitation: reducing collective count/startup changes the communication implementation, not merely removing a redundant dependency; it must preserve all top-k and output semantics. Conversely, rank-local asynchronous completion may only hide work already overlapped by compute.
- Current evidence: historical EP4 AG/RS controls measured per-round/network effects, but no calibrated decomposition proves an avoidable current-version startup term or serving-level headroom specific to owner readiness.
- Decision: `NO_SEPARATE_CANDIDATE_ESTABLISHED`; do not optimize a constant or zero an approximately 10.2-µs historical intercept without matching the backend/runtime.

## Overall

Neither backup currently has the route/profile/critical-path evidence needed for a strict theory gate. They remain future audit questions, not reasons to start another parameter sweep.

