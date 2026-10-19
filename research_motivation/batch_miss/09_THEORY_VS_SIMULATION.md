# Theory versus serving-integrated FlowSim

| Quantity | Analytic/model-derived | E3a: KV isolated | E3b: FAIR shared | Result |
|---|---|---:|---:|---|
| Old active Decode requests | 6 per receiving lane; one free slot | 6 | 6 | candidate makes7/8; not GPU utilization |
| Concurrent candidate P2D requests | R1 + 3 R2 | 4 | 4 | four distinct source GPUs on one rail |
| EP communicator | one legal EP4 group | one | one | current AG/RS, not GateRouter A2A |
| KV bytes/request | 48×4MiB | 201,326,592 | 201,326,592 | exact model-derived |
| Candidate KV bytes total | 4×request bytes | 805,306,368 | 805,306,368 | exact model-derived |
| Directed shared rail | 200G=25GB/s | same | same | actual common route `30->26` |
| One 4MiB layer solo floor | B/C | 177.973µs | — | measured includes modeled hop latency |
| Ideal four-flow group layer time | 16MiB/C=671.089µs | target last FCT681.289µs | target last FCT684.649µs | E3a added vs solo=503.316µs; FAIR adds3.360µs more |
| Average rail KV demand | four requests /72.474ms | — | ≈11.11GB/s =44.4% | burst utilization reaches1; bursts drain between releases |
| R0 Decode batch period | profile/run determined | ≈8.431ms | ≈8.431ms | measured consecutive completion interval |
| Prefill graph finish | event |128.817ms |128.817ms | direct sampler and graph event |
| Last required KV finish | max shard |127.651289ms |127.654649ms | ΔFCT=3.360µs cross-class |
| Hidden compute slack | compute finish − KV finish |1.165711ms |1.162351ms | absorbs critical-shard completion |
| P2D-ready | actual dependency join |128.817ms |128.817ms | `Delta_ready=0` |
| Ready-to-Batch9 slack | decision − ready |1.256992ms |1.411511ms | no crossing |
| First batch ID | scheduler event |9 |9 | same membership |
| Batch9 selection | scheduler event |130.073992ms |130.228511ms | FAIR is154.519µs later |
| TTFT | arrival→first visible |98.817ms |98.817ms | unchanged |
| TTST / first Decode ITL | first→second visible |10.639704ms |10.794223ms | +154.519µs (+1.452%), EP/batch timing |
| SLO sensitivity attainment | relative to E3a TTST |4/4 all thresholds |4/4 all thresholds | controlled n=4 only, not population SLO |

The synchronized-flow theory correctly predicts the P2D shard service inflation at the measured bottleneck. The end-to-end hypothesis fails because Prefill completion remains the max/join gate. For this exact phase/workload, even eliminating all network interference avoids zero batch misses. Effects at other phases or larger prompts are not analytically determined by this matched result.
