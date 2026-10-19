# 10 — Final GO / NO-GO

## Classification

**Mechanism label:** `DECODE_OPPORTUNITY_EFFECT_CONFIRMED`

**Research/algorithm decision:** `NO_GO_FOR_NEW_ONLINE_SCHEDULER`

The classification is intentionally two-part. In the primary controlled integrated run, request 3's model-derived P2D handoff finishes before a naturally generated D0 slot opens, while FAIR finishes after it. The next Decode batch starts 3.381 ms earlier and the modeled second-token/request-completion event also occurs 3.381 ms earlier. The same qualitative absolute improvement occurs with an 11-token D0 seed. This confirms a real event-chain mechanism inside this simulator.

It does **not** justify an online Decode-Opportunity-Aware KV Handoff algorithm or a paper claim at this stage:

1. With a 13-token D0 seed, the Decode slot stays occupied past both policies' P2D-ready times and the second-token difference shrinks to about 43 μs. The effect is a narrow slot-boundary condition.
2. Pair-mean arrival-to-second improves only about 0.85%, overall makespan about 0.014%; the benefit is concentrated in one request while the other lane is occupied much longer.
3. The simulator's reported TTST worsens in the main comparison; the sampler-boundary diagnostic improves, but there is no client-visible first-token callback to validate it as true TTST.
4. Each target contributes one TBT interval only; target TBT percentiles and SLO attainment are not measured.
5. The selected-request control uses offline knowledge of the next Decode opportunity. FIFO/SRPT/coflow tie ordering misses this specific choice, but EDF/LLF/Nuska-style request urgency could plausibly encode it; those complete baselines were not run. No incremental advantage over established methods is proven.
6. TP2/EP2 AG/RS and a 2P/2D fluid topology are a mechanism case, not evidence for high-degree sparse MoE collectives or production frequency.

## Answers to the ten required questions

1. **TP-rank correction and contention:** TP2/EP2 removes the former TP2/EP1 compute skew. Each target has two equal 100,663,296-B shards; one per request crosses the shared directed cut. Under FAIR, the target request barrier is ~8.089 ms, versus ~4.05 ms for the first grouped request.
2. **FAIR vs request grouping:** selecting request 3 changes its P2D-ready by −4.038 ms; selected request 2's ready is ~9.4 μs later than FAIR in the full EP run. The isolated network-only coflow bound is ~4.029 ms vs ~8.055 ms for the selected request.
3. **Different Decode opportunities:** yes in the primary controlled seeds: D0 frees at 75.586 ms, D1 at 315.531 ms. The one-token neighbor check shows how quickly that advantage disappears when the slot ordering changes.
4. **Batch attribution:** no batch ID/membership change was recorded; the same D0 batch id starts earlier. The experiment demonstrates start-time opportunity alignment, not reassignment to a different batch.
5. **Second token:** request 3's event is 3.381 ms earlier in the primary run and ~4.037 ms earlier in the 11-token neighbor. It is only ~43 μs in the 13-token neighbor. This is a simulator event result, not a validated client TTST/SLO percentile.
6. **Cost to other requests:** request 2's P2D FCT increases by ~9.4 μs in the selected opportunity control, but its serving completion is dominated by D1's seed occupancy. Global pair makespan changes by only 43.5 μs; do not market the one-request gain as aggregate goodput.
7. **EP feedback:** earlier request admission adds EP traffic while request 2's P2D remains active, but the measured other-request KV FCT penalty is only ~9 μs. Material feedback coupling is not confirmed. Conversely, strict KV_FIRST produces a large EP outlier and delays D0's slot.
8. **FIFO/SRPT/EDF/Coflow:** the CSV explicitly records only a tie-equivalent request-2-first ordering for FIFO/SRPT/coflow; no independent implementations were run. EDF/LLF and complete Nuska are not evaluated. Classic scheduling sufficiency is unresolved; novel incremental headroom is therefore unproven.
9. **Novelty:** the mechanism is adjacent to Varys/coflow, Nuska/MFS and STORM; the experiment is insufficient to distinguish a new algorithm from application-aware deadline/opportunity scheduling. No CCF C/B paper direction is validated.
10. **Continue?** Do not proceed to scheduler implementation based on this result. If the project continues, first repair/extend token visibility semantics and run only a direct, matched EDF/LLF/Nuska/coflow comparison in this same small setup. Stop if those baselines match the offline opportunity bound.

## Safe conclusion

The validated observation is:

> A P2D handoff can be network-complete early enough to catch a Decode lane's next admission slot; if that slot is missed, Decode capacity wait can absorb the network-level improvement. This timing effect is conditional on the relative phase of P2D readiness and Decode-slot release.

The evidence does not show that this is frequent in real serving, does not establish robust TTST/TBT/SLO gains, and does not show a new scheduling opportunity beyond existing deadline/request-aware methods. This is a useful characterization result and a candidate integration requirement, not a CCF paper-ready motivation.
