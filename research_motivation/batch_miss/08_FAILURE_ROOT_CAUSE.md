# Failure diagnosis by causal stage

## Observed mechanism

The physical shared-cut mechanism is real: the four P2D streams and EP flows have overlapping active intervals on a common directed ToR cut. Four concurrent P2D requests raise request24's last-shard FCT from177.973µs (E0 solo) to681.289µs in E3a; physical FAIR with EP gives684.649µs. The E3b cut `30->26` reaches utilization1. Maximum `fluid_outstanding_bytes` in the selected window is16,723,066B on `24->30` and8,371,534B on `30->26`. These values are analytical residual fluid, not packet-buffer occupancy.

## Earliest failed causal edge: F3

In E3b the last required layer47 shard finishes127.654649ms; final Prefill sampler/graph finishes128.817ms. The remaining compute gate is1.162351ms. E3a has1.165711ms. Adding physical EP sharing changes the target critical-flow FCT only3.360µs, and both variants finish before the same Prefill completion. Thus `Delta_ready=0`.

This is **F3: network FCT changes but P2D-ready does not**. It also fails F4's antecedent (`Delta_ready>0`), so the measured network delay cannot cross the next-batch boundary. The target is eligible before batch9, has a sequence slot, ample KV blocks and token budget, and is selected into batch9 in both cases.

## Serving-visible change is small and not a KV admission miss

E3 FAIR vs KV_ISOLATED TTST changes10.639704→10.794223ms (+154.519µs, +1.452%). EP CCT mean changes11.045→11.146µs (+0.91%); P99 changes11.347→11.675µs (+2.89%). TTFT remains98.817ms. Because ready is identical, the TTST increase follows recurring EP service shifting completion of the previous Decode iteration and the next batch selection. It is not attributable to P2D-ready.

## Failure-type disposition

- F1 (no offered network load): not the main failure. Average KV load across the layer-release span is about44.4% of one rail, but individual layer bursts saturate it and queue residual exists.
- F2 (no physical sharing): ruled out for the selected target; exact paths and interval overlap exist.
- F3 (last shard hidden behind compute): confirmed, with1.162351ms remaining compute slack.
- F4 (ready delayed but not enough to miss): not reached; `Delta_ready=0`.
- F5 (actual scheduler boundary differs from assumed): not observed; logs identify Batch8 completion and Batch9 selection at the same event boundary, and R1 enters batch9.
- F6 (miss but no user-visible effect): no miss occurred.
- F7 (TTST shift from another source): small +154.519µs is explained by EP/batch service; TTFT/readiness invariant.
- F8 (narrow phase): phase scan not run. No positive ready delta exists to justify it; no phase probability claim is made.
- F9 (theory/simulator mismatch): no gross mismatch at the tested point. Ideal 4-flow per-layer extra is503.316µs; E3a observes exactly503.316µs over the solo-shard service. FAIR adds a further3.360µs on the critical flow. The gap to ready is measured Prefill slack.

The planned maximum workload (one R1 plus three same-size R2s, one per active Prefill GPU) has been exercised. Since the first necessary edge `network → P2D-ready` is zero, further byte/load/bandwidth manipulation or forced phase alignment would exceed the bounded search without evidence.
