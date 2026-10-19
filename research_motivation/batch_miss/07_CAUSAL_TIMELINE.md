# Causal timeline: network events to batch membership

Authoritative rows are in `results/07_EVENT_TIMELINE.csv`; per-flow timing and path in `results/07_KV_FLOW_LEDGER.csv`; positive-time KV/EP shared-directed-link pairs in `results/07_KV_EP_SHARED_LINK_OVERLAPS.csv`; selected per-link fluid state in `results/07_LINK_FLUID_TIMESERIES.csv`. Full selected scheduler and graph ledgers are retained under `results/`.

## E3, four simultaneous P2D requests, FAIR

| Time | Event |
|---:|---|
| 54.349ms | R1/R2 Prefill compute starts; old Decode batch0 begins |
| 54.496ms | first candidate P2D layer release |
| 126.970ms | layer47, last KV layer, is requested |
| 127.654649ms | R1's last required P2D shard finishes |
| 128.817ms | Prefill sampler/graph completes; `P2D_READY` and Decode eligibility |
| 130.228511ms | old Decode batch8 completes; scheduler selects/submits batch9 |
| 139.611223ms | batch9 completes; second token visible, TTST=10.794223ms |

Request24's critical flow is layer47, 4,194,304 B, path `0->24->30->26->8`. Its last-shard FCT is684.649µs. Full request handoff span is73.158649ms, dominated by the72.474ms layer-release span. The last flow still finishes1.162351ms before the Prefill sampler. `t_ready` is compute-gated, so `Delta_ready=0`.

## Matched four-KV comparison

E3a `KV_ISOLATED`: last target FCT681.289µs; last finish127.651289ms; ready128.817ms; batch9 at130.073992ms; second token139.456704ms.

E3b `FAIR`: last target FCT684.649µs; last finish127.654649ms; ready128.817ms; batch9 at130.228511ms; second token139.611223ms.

The network counterfactual changes critical-shard FCT by3.360µs but leaves ready and batch ID unchanged. The154.519µs later Decode batch/second-token event tracks recurrent EP service and the previous batch boundary, not a KV-ready miss.

## Bandwidth and temporal controls

400G FAIR: target critical shard FCT346.585µs, `P2D_READY` remains128.817ms, and R1 still joins batch9. Capacity nearly halves layer-flow completion but does not expose it beyond Prefill compute.

E4 staggered: R1 last shard127.149653ms; R2 first layer release130.147ms. Target FCT179.653µs, equal to the one-target FAIR case. This verifies that extra P2D concurrency explains the E3 KV FCT rise. E4 TTST is10.674222ms; the residual small variation is Decode EP timing, so E4 is not treated as an EP-free control.
