# Final gate decision

## Selected outcome

**`KV_HANDOFF_EXPOSURE_CONFIRMED`** — narrowly, for the corrected POST_PREFILL FlowSim configuration and the matched one-versus-four request comparison. This is a mechanism confirmation, not a paper GO.

**Paper decision: NO-GO for a new request-coflow/network-priority algorithm from this result.** The observed integrated effect is modest (+5.8568% TTFT for matched request 0 when a second same-rail P2D request is added); actual-anchor offline grouping changes mean handoff by 3.396%, leaves the maximum/P99 unchanged, and is equivalent to FIFO/SRPT/coflow in this equal-size case. The serving scheduler version of that grouped policy was not run, and no active Decode EP overlaps the KV interval.

## Answers to the causal question

1. **Does Flow-level FAIR delay request-level required KV completion?** Yes in this controlled run. Two same-rail 96-MiB TP shards released in the late wave complete in 8.063264 ms under two-request FAIR versus 4.036732 ms for the matched single-request run.
2. **Does that reach Serving?** Yes. The matched request's P2D-ready, Decode admission, first visible token, and TTFT all shift by 4.026532 ms (+5.8568%).
3. **Does request grouping recover a meaningful tail?** Not demonstrated. The actual-anchor replay improves mean completion only and leaves the maximum ready timestamp unchanged. Do not treat the simultaneous-release 24.984% bound as measured or as TTFT gain.
4. **Is the effect KV–EP?** No. This evidence is cross-request KV–KV contention. The four requests all complete P2D before their first EP collective begins.
5. **Is there a distinctive policy opportunity beyond classic scheduling?** Not shown. FIFO, request-SRPT and coflow-FIFO yield the same replay ordering. No EDF deadline exists in the workload.
6. **Is this production-representative?** Not established. It is a deterministic, model-derived controlled case. The Prefill TP-rank release gap (51.216 ms) arises from the EP1/TP2 MoE trace-rank mapping and is an important model caveat.

## Gate summary

| Gate | Status | Decision |
|---|---|---|
| G0 transfer semantics | PASS with caveat | Integrated POST_PREFILL and completion feedback work; per-rank release is not atomic |
| G1 fixed-resource network opportunity | PASS, bounded | Same-rail FAIR sharing changes last-shard service; ideal simultaneous-release oracle is not actual workload |
| G2 Serving exposure | PASS, modest | Matched TTFT +5.8568%; TPOT/TBT unchanged |
| G3 nontrivial optimization headroom | FAIL / insufficient | Grouped replay changes mean, not maximum; no integrated grouped run justified |
| G4 novelty | FAIL for this candidate | Direct overlap with coflow and stage/request-aware scheduling; no decision divergence |
| Background Decode EP test | NOT RUN / not applicable | No EP overlaps P2D; no KV–EP conclusion |
| Layerwise fan-in extension | NOT RUN | Conditional gate not reached |

## Final conclusion

Keep the result as a small correctness/mechanism data point: request-level P2D completion is a max-over-required-shards barrier, and same-rail cross-request sharing can shift TTFT when the transfer is POST_PREFILL and exposed. Do not expand load, add a scheduler, or claim a CCF paper motivation from this result. The immediate research action is to preserve the accurate negative/bounded result and resolve the Prefill TP-rank trace mapping before using this configuration for broader claims.
