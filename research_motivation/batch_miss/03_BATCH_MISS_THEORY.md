# Batch-miss condition and quantitative bound

For request 24 in the four-P2D matched experiment:

- `t_prefill_finish = 128.817000ms` (directly observed at the final Prefill sampler node and graph completion).
- `t_kv_last = 127.651289ms` in the within-KV-isolated class control; `127.654649ms` in physical FAIR.
- The serving handoff uses the Prefill-graph completion callback after required P2D dependencies; observed `t_ready = 128.817000ms` in both runs, i.e. compute dominates the max/join.
- `t_batch_9 = 130.073992ms` isolated and `130.228511ms` FAIR; Batch 8 is still executing until that event.
- R1 has slot/block/token-budget eligibility and is selected into Batch 9 in both runs.

## Two different slack values

1. **Compute-hidden KV slack** relative to the measured four-request `KV_ISOLATED` baseline: `t_prefill_finish - t_kv_last = 1.165711ms`. The FAIR last shard is1.162351ms before the same compute gate. Another1.165711ms of last-shard completion delay is required before P2D-ready moves at all.
2. **Ready-to-next-batch slack** in the isolated run: `t_batch_9 - t_ready = 1.256992ms`. To cross this particular selection event after consuming compute slack requires more than `1.165711 + 1.256992 = 2.422703ms` of additional last-shard completion delay relative to E3a. Merely delaying a shard by1.256992ms is not sufficient if the first1.165711ms remains hidden by Prefill compute.

For4MiB messages, the synchronized equal-flow ideal adds167.772µs for each additional active flow. Relative to the measured E3a N=4 state, N=11 is the first integer whose ideal extra delay exceeds the1.165711ms compute slack (N=10 adds1.006632ms; N=11 adds1.174404ms, exposing only8.693µs of ready delay). N=18 adds2.348808ms over E3a: after compute masking it moves ready1.183097ms, still73.895µs before Batch9. N=19 adds2.516580ms over E3a and projects ready1.350869ms later, crossing Batch9 by93.877µs. The ideal group would carry76MiB on that layer. These are synchronized, fixed-slack lower-bound calculations only, not end-to-end predictions. The current one-graph-per-Prefill-rank and2,048-token per-batch budget permits at most four simultaneous full-size2,048-token streams in this topology (one per active Prefill GPU); splitting a rank's2,048-token budget among smaller requests does not increase aggregate bytes. Measured layerwise P2D drains before the next same-rank Prefill graph can create another full stream. Thus the synchronized N=11/19 full-size conditions are outside the tested legal concurrency envelope.

The batch-miss necessary condition is `Delta_ready > 1.256992ms` for the observed boundary, plus unchanged capacity and budget eligibility. A request merely arriving while Batch 8 executes is not a miss if it becomes ready before Batch 9 is built.

## Phase-probability model and its limits

If readiness phase were uniform over a stable measured period T=8.431ms, a fixed positive ready delay Δ would give the rough phase-crossing probability `min(1, Δ/T)`. Hypothetical values: 0.2ms → 2.37%; 0.5ms → 5.93%; 1.0ms → 11.86%; 1.256992ms → 14.91%. These are formula sensitivities, not measured probabilities. The workload is controlled and synchronously released, with one phase point; no uniform-phase assumption is validated. The observed `Delta_ready=0`, hence the observed phase-conditioned miss count is 0. A phase scan was therefore not run.

For the observed workload, even a clairvoyant policy that eliminated all network interference has zero avoidable network-induced batch misses: both counterfactuals already select request 24 into Batch 9. Any population-level miss rate or potential SLO gain outside these tested points is `NOT_ANALYTICALLY_DETERMINED`.
