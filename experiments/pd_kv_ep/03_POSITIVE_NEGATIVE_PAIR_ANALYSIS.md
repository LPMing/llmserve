# Positive/negative paired evidence

## Pair 1 — Controlled EP64 positive vs natural EP64 negative

Both use corrected S16, Qwen3-30B-A3B, EP64, model-derived A2A_P2P and LAYERWISE KV. The controlled run has 32 Decode requests warmed at t=0 and 64 new 2048-token P2D requests released together at 20ms. FAIR to EP_FIRST changes EP CCT P99 from 92.279 to 45.644us (-50.54%), TBT P99 from 8.862 to 6.937ms (-21.72%), and TPOT by -17.26%; P2D KV-ready is unchanged. This establishes that a network policy effect can cross the Decode iteration barrier when timing and active cohorts create exposure.

Natural Azure Conversation-16 and Code-32 retain original timestamps/token sizes. FAIR to EP_FIRST changes EP CCT P99 by 0% and TBT P99 by 0% and -0.275%; TTFT P99 changes -0.0017% and -0.0076%. Last KV completion precedes Prefill completion by median 1.17–1.25ms; Decode ready-to-first-batch wait peaks at 8.75%/6.72% of TTFT.

What changed: cohort alignment and cross-class offered load/overlap, not model bytes or link rates. The natural windows did not develop an EP_FIRST-sensitive queue/barrier. Controlled alignment is a mechanism control, not evidence of its production frequency.

## Pair 2 — POST_PREFILL vs LAYERWISE

LAYERWISE releases KV shards as layers are computed; later releases provide overlap slack for earlier shards. POST_PREFILL releases the complete P2D only after Prefill work, removing that overlap. D64+K1 residual-drain penalty is +19.51% under POST_PREFILL and TTFT +4.62%; adjacent D32 gives +10.47% drain and +3.30% TTFT. TBT P99 movement remains under 1%. This is consistent with extra network delay becoming more exposed when generation slack is removed, but control-matching caveats mean it is not a production architecture comparison.

The dependency changed: P2D release moved after compute and the last-KV barrier became more directly exposed. Network queue alone does not explain TTFT; integrated event segmentation is required.

## Pair 3 — Shard FCT vs request handoff

In the frozen S8 CC_MODE=1 packet ledger, per-request KV shard P99 rises +101.3% (K8) and +90.9% (K9) under two concurrent K requests versus per-request isolation. Request handoff changes only +11.637us (+0.0040%) and -41.312us (-0.0141%). In matched CC_MODE=1 vs unsupported legacy mode 12, shard FCT P99 rises about 189–200%, while request handoff P99 changes <0.8%. Handoff is the maximum completion among required shards, not the sum of shard FCTs.

Why hidden: 383/384 K8 shards complete by final-layer release; CNP-hit shards have about 165.5ms average slack to the request barrier. Even the same final layer-472 shard changes completion by only 119.677us across valid CC1-vs-CC0. Large flow slowdown is not automatically a large barrier shift.

## Pair 4 — Early shard vs final shard

An early shard has release-to-barrier slack while later layers compute/release. In S8 attribution, most early shards complete before final-layer release. The final required shard has zero max-barrier slack by definition, but its extra delay can still fit before Prefill completion: +23.568% residual drain coexists with +0.0115% request handoff, and final shard finishes 2.367ms before Prefill completion. “Final layer” does not mean “TTFT critical”; compare its finish to all other shards and next serving event.

## Pair 5 — Static priority controlled vs natural

Controlled EP64: EP_FIRST reduces EP CCT P99 and TBT P99 substantially, KV-ready unchanged. Natural Azure: same policy toggle has nearly zero effect on EP, KV-ready, TTFT, TBT and TPOT. Conversely, KV_FIRST can dramatically delay EP: in the small EP4 integrated case EP CCT P99 rises 11.860→148.982us but TBT P99 only +8.3%; S8 packet EP32 KV_FIRST raises EP CCT P99 +852.9% while request handoff remains almost constant. Traffic-class priority changes network service, while serving criticality depends on which barrier is awaiting the delayed communication.

## Pair 6 — EP peer FCT vs collective CCT vs token TBT

A slow peer matters to a collective only if it is last or pushes the last peer later. EP CCT is max peer finish minus collective start. The collective can still be hidden by compute/batch work. In corrected S16 packet fan-in, peer-flow FCT P99 increases +34.9% and CCT P99 +29.1%; the separate integrated FlowSim point shows TBT P99 +5.01%. This is directionally consistent with barrier filtering but is not same-run packet-to-serving causality. Controlled EP64 integrated runs show a case where CCT and TBT both move; natural Azure does not.

## Pair 7 — Queue episode vs serving barrier

At the minimal 1P2D/EP16 shared ToR, there is measured shared directed ingress overlap. At D16+K8, P95 positive fluid-queue episode is 3.258us and median EP period 6.237ms, ratio 0.000522. EP CCT P99 rises 5.11%, KV residual P99 3.66%, TTFT +1.60%, TBT +0.47%. Short queue episodes and layerwise release slack prevent a persistent barrier shift. FlowSim queue is analytical fluid backlog, not a packet buffer.

The 512-request FlowSim fan-in case has larger network barrier deltas (EP P99 +201%, KV P99 +99%) but no integrated serving result. High utilization, ECN count, queue, or overlap cannot stand in for a serving measurement.

## Cross-pair conclusion

The best predictor is not raw bytes, utilization, ECN count, flow P99, or traffic class. It is the delayed object's distance to the next dependency barrier, plus whether that barrier is exposed to TTFT/TBT. Exact confirmation of a proposed optimization requires same-run integrated counterfactuals. The evidence currently supports the explanation, not a new scheduler.

## Pair 8 — Route coactivity vs critical-path exposure (natural Azure Code n44)

The first 44 requests of Azure Code window 013818 were replayed with the same
arrival/token prefix and configuration as the retained n64 run. The n44 trace
exactly matched all serving-iteration, EP-collective, and KV-flow records
through 475ms, while allowing complete targeted link telemetry. In 463–466ms,
42/42 EP collectives had a critical-peer route that shared a directed FlowSim
link with active P2D KV. Yet their mean CCT was 34.233us and P99 45.644us; in
the wider 450–475ms grouping, coactive events had a lower unmatched mean than
noncoactive events and identical P99. Thus route coactivity is necessary to
test a shared-resource mechanism but not sufficient to show harmful exposure.

The KV request whose last shard fell in the target window still had 1.271ms
until Prefill completion. The nearest collective-to-logical-iteration finish
gap was 0.228ms, but that is not an exact per-collective dependency slack.
There is no matched counterfactual delay, so neither gap can be converted into
an exposure ratio. This strengthens the negative/control evidence without
falsifying the general slack hypothesis.

## Pair 9 — Trace-preserving arrival compression (Azure Code n44)

The same first 44 Azure Code requests were replayed with every inter-arrival
interval divided by 1.5. Request IDs, order, input/output tokens, model-derived
KV/EP bytes, topology, routing semantics, LAYERWISE dependencies, and FAIR
service were unchanged. This is an offered-load diagnostic, **not** a
capacity-calibrated `rho` point.

The integrated results remain weak: EP CCT mean rises 3.00%, but EP CCT P50,
P95, and P99 are unchanged; KV handoff slack changes by only +0.744us on
average (median/P95 unchanged); TTFT P99 rises 0.22%, TPOT P99 1.95%, and
token TBT P99 5.05%. All requests still finish KV handoff before Decode. The
global active Prefill/Decode peaks increase from 8/12 to 13/14, while the
arrival-to-first-schedule queue-delay distribution is unchanged. The
route-coactivity fraction decreases from 16.96% to 15.89%, so compression did
not increase the candidate's critical-route overlap fraction.

This does not establish that joint scheduling lacks value at calibrated load:
the finite prefix has no sustainable-capacity denominator, and the full-run
link sidecar truncates at 5.874ms. It does show that this particular
trace-shaped perturbation did not produce a serving-visible barrier crossing.
Do not infer full-run link utilization or queue behavior from the partial
sidecar, and do not treat the observed finite-prefix completion rate as
capacity.
