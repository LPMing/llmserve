# Failure/root-cause accounting

The status distinguishes actual negative evidence from untested hypotheses. “Not tested” is not converted into a pass or a simulator defect.

## H1 — same-class EP group urgency

| ID | Hypothesis | Evidence / number | Status and interpretation |
|---|---|---|---|
| F1 | The two groups are not legal independent EP groups | Two distinct `dp_group`s; four participants and twelve peer flows per group collective; separate barriers | **Not the cause.** The existing small case is legally represented within the current supported layout. |
| F2 | Groups do not share a directed bottleneck | 2,976 paired group/phase rounds; all paired releases equal; all dispatch/combine intervals intersect on the common D0↔D1 path | **Not the cause.** Shared cut and temporal overlap are confirmed. |
| F3 | Effective EP cut bytes are too small | At 4 requests/group: 17,408-B dispatch and 8,192-B combine per directed cut; at group64/context2048: 139,264/131,072 B | **Primary limitation.** The maximum profile-derived same-shape ceiling is 519.045 µs/token (3.07% at context2048), and is not differential urgency headroom. |
| F4 | More bytes bring proportionally more compute | Group64/context2048: 519.045 µs ideal work against 16.899-ms profile token interval; context8192 denominator grows to 23.817 ms | **Contributes.** Larger batches raise cut work, but model compute also grows and caps relative benefit. |
| F5 | Different compute timings de-align collectives | Context64-group pair 256/512: only 5 of 96 cut-service phase events intersect; max 27.197 µs each. Full heterogeneous 132-pair screen max target-A is 53.412 µs | **Primary urgency limitation.** Distinct work reduces overlap; maximum optimistic group-specific gain is 0.3161%. |
| F6 | Network CCT is not on token critical path | In the existing homogeneous integrated case, 48×(dispatch delta+combine delta) equals observed +41.280/+49.152 µs token interval | **Not the cause.** The network delay reaches TBT in this fixture; its total percentage is small. |
| F7 | Group priority helps some flows but not token completion | No request/group priority oracle run because G1 failed | **Not tested; gated.** No such serving gain is claimed. |
| F8 | Groups have equal urgency / no avoidable SLO conflict | Homogeneous FULL groups have identical 31-ITL sequences. Heterogeneous candidates have only sub-0.32% optimistic headroom; no grounded SLO | **Primary motivation failure.** A metric distinction can be made by context/batch, but there is no material, SLO-grounded opportunity in the tested envelope. |
| F9 | Priority A worsens B's deadline miss | No group-priority schedule or frozen SLO | **Not tested; gated.** |
| F10 | SJF/SRPT/EDF/LLF already match a group oracle | No such baseline was run | **Not tested; gated.** Do not claim these policies were beaten or matched. |
| F11 | Frozen oracle looks optimistic but integrated run fails | No oracle/integrated run after G1 | **Not tested; gated.** The documented phase upper bound explicitly does not model feedback. |

## H2 — KV request urgency

| ID | Hypothesis | Evidence / number | Status and interpretation |
|---|---|---|---|
| F12 | Request-level max KV shard changes materially | 128-token victim shard P99 +25.35%, but the recorded last completion remains before ready | **Partly present at shard-level only.** No request-barrier delay follows in those runs. |
| F13 | Prefill masks last-required KV delay | Slack: 1.094 ms (small victim), 1.419 ms (2,048 background), 1.796 ms (8,192 background); A7 candidates 0.654–0.794 ms | **Observed root cause.** Last KV is not the max predecessor of readiness. |
| F14 | Ready moves but fails a scheduler decision boundary | A7 first recorded Decode decision is +1.707/+3.532 ms from baseline ready; +1.5-ms extra last-KV arithmetic remains below both | **No crossing in tested arithmetic range.** No delayed replay was run, so not a simulated policy result. |
| F15 | Prioritizing A steals B slack | Request-priority replay not run | **Not tested; gated.** |
| F16 | Existing workload lacks network-exposed handoff | All inspected candidates show last KV completion < P2D-ready | **Observed for these fixtures.** This is a bounded negative, not a universal claim. |

## First gate failure

H1 first fails at **differential exposed opportunity**, not topology or legal collective generation: groups share the cut and their collective changes do propagate to TBT, but same-urgency alignment is the only case with a multi-percent ideal ceiling. The strongest heterogeneous candidate is below 0.32% even before real schedule feedback. H2 first fails at **last-required-KV criticality**: measured delays remain inside compute masking slack, and the candidate's recorded next Decode decision is later still.

Neither branch exposes evidence of a simulator/integration correctness defect in the particular ledger under review. Limitations (AG/RS instead of sparse A2A; transient raw file; missing B-alone and policy controls) remain explicitly recorded.
