# 02 — Quantitative serving-critical-path headroom

## Bottom line

The project has repeatedly demonstrated **network-level contention**, but the
largest effects do not generally cross a request/token barrier. The only
strong end-to-end result is a deliberately controlled EP64 exposure point; it
proves possibility, not natural frequency or a global scheduler opportunity.
For the frozen old-line gate, no natural two-window evidence supports ≥5%
global improvement over a strong feasible baseline without collateral cost.

## What the request barrier can expose

For a request with a fixed Decode lane-free time, let `tK` be P2D-ready and
`tK'` a hypothetical earlier P2D-ready. A screening bound is:

`G_upper = min(max(0, tK - tK'), max(0, tK - lane_free))`.

This is a **frozen-event filter**, not a strict bound once the policy changes
other requests, Decode lane release, batch membership, or future EP issue times.
The source calculations are in
[`02_PER_REQUEST_HEADROOM.csv`](02_PER_REQUEST_HEADROOM.csv). For the primary
controlled Decode-opportunity seed, request 3 has a 4.038ms P2D-ready advance
under the special request-first policy; its baseline D0 lane is free at
75.610ms and baseline KV-ready is 78.966ms, so the frozen-lane exposed gap is
3.356ms. The measured arrival-to-second event advances 3.381ms; the ~25µs
difference is because lane/seed completion itself changes, illustrating why
the screening equation is not a substitute for integrated replay.

The 11-token neighbor is similar (~4.037ms for the target), while the 13-token
neighbor collapses to ~43µs because both policies miss the earlier Decode
opportunity. Thus the large single-request delta is phase-sensitive. With two
new requests, pair-mean arrival-to-second improves only ~0.85%; the global
makespan change is ~43.5µs. Each target has one TBT interval, so request-level
TBT tail percentiles are not estimable.

## Headroom by mechanism (do not combine rows as one experiment)

| Mechanism and matched comparison | Network-side result | Serving-side result | Frozen interpretation |
|---|---|---|---|
| KV–KV, short request vs long KV | Shard FCT P99 up to +25.35% | Request last shard/P2D-ready and TTFT unchanged in the cited cases | Most shard delay is absorbed by layerwise release slack; the last required shard controls handoff. |
| KV–EP controlled EP64, FAIR→EP_FIRST | EP CCT P99 92.279→45.644µs (−50.54%) | TBT P99 −21.72%, TPOT −17.26%, KV-ready unchanged | Valid controlled exposure; not a natural-arrival incidence claim and not evidence that EP_FIRST hurts KV. |
| EP–EP, two independent EP4 groups, FAIR | Dispatch CCT +6.39%; combine +1.58–3.11% | TPOT/TBT +0.75–0.80%; TTFT unchanged | Recurrent barriers expose the effect, but the serving fraction is small; this experiment uses AG/RS, not routed sparse A2A. |
| Shared NIC class priority, FAIR→EP_FIRST | EP CCT tail improves; EP_FIRST approximates isolated EP in this fixture | Mean TPOT about −0.61%; ITL P99 unchanged | Little incremental headroom beyond static class protection. |
| Minimal ideal 1P2D/EP16 D16+K8, FAIR | EP CCT P99 +5.11%; KV residual +3.66% | TTFT +1.60%; TBT +0.47% | Even favorable 200G shared-ToR point did not expose a large barrier shift. |
| Controlled Decode opportunity, one request | Target KV-ready −4.038ms | Arrival-to-second −3.381ms in primary seed; pair mean −0.85%; 13-token neighbor ~43µs | A narrow slot-boundary mechanism, with incomplete user-visible TTST semantics and small global gain. |
| Heterogeneous EP group urgency, profile bound | ≤53.412µs target-group removable time | 0.3161% of the slower token interval in the maximum heterogeneous screened pair | Optimistic analytical screen only; no policy oracle was run. |
| Natural Azure Code 013818 first 44 | 21.61% of collectives have critical-route same-link coactivity | All 44 KV handoffs precede Prefill completion; minimum Prefill slack 0.709ms; no matched CCT increase | Coactivity is not barrier exposure. |
| Natural Azure Conversation 06210 first 16 | 1.783% critical-route same-link coactivity | All 16 last-KV completions precede Prefill completion; minimum slack 0.709ms | No request-level KV criticality was observed. |

## Required upper-bound categories

| Requested comparison | Status | Quantitative statement |
|---|---|---|
| FAIR → network isolation | `MEASURED_ONLY_IN_SEPARATE_CONTROLLED_CASES`; natural candidate isolation not run | In the controlled EP64 case, EP_ONLY/isolation-like comparison is not interchangeable with the FAIR→EP_FIRST integrated result. For natural Azure request handoffs, observed last-KV timing has positive Prefill slack; an exact counterfactual upper bound was not measured. |
| FAIR → EP_FIRST | `MEASURED` in controlled and selected natural prefixes | Controlled EP64 TBT P99 −21.72%; natural 16-window policy deltas are near zero (e.g. Azure Code/Conversation earlier matched results: TBT P99 0%/−0.275%, TTFT P99 −0.0017%/−0.0076%). These are not pooled. |
| FAIR → request/coflow completion oracle | `NOT_RUN` for the natural frozen windows | Historical equal-size coflow/FIFO sensitivity does not substitute for the final natural-window oracle. |
| FAIR → serving-aware offline oracle | `NOT_RUN` / `NOT_COMPUTABLE` globally | The Decode-opportunity diagnostic is narrow and uses offline timing; it is not a full schedule oracle with collateral accounting. |
| EDF/LLF/SRPT/complete Nuska comparison | `NOT_RUN` for the final natural windows | The frozen exposure/headroom gate fails; no claim is made that those methods have zero gain or were beaten. |

## Client-visible metric caution

The existing simulator records sampler completion, P2D-ready, Decode
admission, and second-token events. It does not provide a separately validated
client wire callback for the first token in every historical path. The
decode-opportunity CSV's `sampler_to_second_diagnostic` is explicitly not
user-visible TTST. The target request in the main controlled case has one TBT
sample. Therefore the 3.381ms arrival-to-second result is a serving-event
diagnostic—not a request P99/SLO claim.

