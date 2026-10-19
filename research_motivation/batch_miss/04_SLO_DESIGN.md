# TTST and SLO measurement design

## Metric semantics

The model makes the first token visible at Prefill completion. `TTST = second_token_visible - first_token_visible`; here the second token is produced by the first Decode batch containing the request. Thus TTST includes the wait from Prefill completion to the next legal batch selection plus that batch's execution. It is not the same quantity as steady-state TPOT. In these records the request CSV's TPOT is 9.08–9.58ms while TTST is 10.27–10.79ms.

TTFT is measured from request arrival to the Prefill-completion first token. For request 24: arrival 30ms; first token 128.817ms; TTFT 98.817ms. P2D-ready also occurs at 128.817ms, but the same timestamp is controlled by Prefill completion. First Decode batch, second token, and capacity-wait are separately exported.

## Reference and sensitivity thresholds

Use the same-workload isolated candidate reference in the four-P2D case: `TTST_ref = 10.639704ms` (E3, KV_ISOLATED; it still allows KV-vs-KV sharing and isolates EP onto an independent virtual capacity copy). Sensitivity thresholds are 1.25×=13.299630ms, 1.5×=15.959556ms, and 2×=21.279408ms. These are explicit relative sensitivity points, not externally grounded production SLOs.

E3 has four target requests, not a population suitable for a production percentile claim. All 4/4 requests satisfy all three sensitivities in both E3 controls; report this as controlled-sample attainment only. No P95/P99 serving-SLO headline is justified. E1/E2 have one candidate each and are similarly diagnostic.

| Case | TTST | TTST vs E3 isolated reference | 1.25× / 1.5× / 2× attainment |
|---|---:|---:|---:|
| E3, KV_ISOLATED | 10.639704ms | reference | 4/4 / 4/4 / 4/4 |
| E3, FAIR | 10.794223ms | +1.452% | 4/4 / 4/4 / 4/4 |
| E3, 400G FAIR | 10.271425ms | −3.462% | 4/4 / 4/4 / 4/4 |

The FAIR-vs-isolated TTST increase is 154.519µs (+1.452%), but P2D-ready is identical; the increase follows slower recurring EP collectives delaying the batch boundary. It is not evidence of a KV-caused batch miss.
