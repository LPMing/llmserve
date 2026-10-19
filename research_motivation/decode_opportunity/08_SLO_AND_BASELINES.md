# 08 — SLO interpretation and baselines

## Metrics that are directly supported

The integrated export contains per-request P2D-ready, decode admission, Decode capacity wait, first Decode batch start/finish, second-token event, reported TTST, sampler-boundary-to-second diagnostic, arrival-to-second, request completion, seed ITLs, and EP CCT mean/nearest-rank P99/max. See `06_SERVING_INTEGRATED_RESULTS.csv` and the compact event/flow ledgers.

For target request 3 in the 12-token D0 calibration:

| Quantity | FAIR | EP-protected selected-request control | Delta |
|---|---:|---:|---:|
| P2D ready / reported TTFT | 78.966384 ms | 74.927908 ms | −4.038476 ms (−5.11%) |
| Decode first batch start | 78.966384 ms | 75.585681 ms | −3.380703 ms |
| Arrival → second-token event | 83.676884 ms | 80.296017 ms | −3.380867 ms (−4.04%) |
| Reported TTST | 4.710500 ms | 5.368109 ms | +0.657609 ms (+13.96%) |
| Sampler-boundary → second-token diagnostic | 12.799067 ms | 9.418200 ms | −3.380867 ms (−26.41%) |

This table is deliberately not collapsed into one “TTFT/TBT gain.” The target's second token / request completion is 3.381 ms earlier in this run. However, the simulator's reported TTST worsens because its TTFT anchor is P2D-ready, while P2D release is also the sampler dependency boundary. The sampler-to-second number is a diagnostic, not client-callback telemetry. The neighbor with D0 output 11 repeats roughly a 4.04-ms absolute second-token gain, while D0 output 13 removes nearly all of it.

Across the two new targets, mean arrival-to-second falls from about 201.981 ms to 200.269 ms (0.85%). Overall completion makespan falls by only 43.52 μs (about 0.014%), and the improvement is concentrated in one target while the other target remains dominated by D1's long seed. This is not evidence of system goodput or aggregate SLO improvement.

## Baselines and what each can claim

- `C0_KV_ONLY_NETWORK`: same serving requests/compute, but network service admits KV only. It is an EP-network-isolated counterfactual, not a separate rerun with different serving semantics. Target FCT is 8.054564 ms.
- `S0_FAIR`: full integrated DAG, neutral fluid sharing; target FCT 8.088567 ms.
- `S1_KV_FIRST_REQ3`: offline selected-request KV-first; target 3 becomes ready at 74.905849 ms but delays the active D0 seed's last EP event and misses the Decode opportunity.
- `S2_EP_FIRST`: global EP-first; close to FAIR for the target KV-ready event because EP's bytes are brief in this setup.
- `S3_FIFO_COFLOW_TIE_REQ2`: request 2 selected first, representing the exact request-ID tie outcome for equal-release/equal-size FIFO/SRPT/coflow ordering. It selects the wrong lane for the early Decode slot.
- `S4_DECODE_OPPORTUNITY_REQ3`: offline upper-bound control that knows which paired Decode lane is about to become free. It is not an online algorithm, and it is not a baseline implementation of EDF, LLF, Nuska or Varys.

## SLO status

No TTFT/TBT SLO thresholds were pre-registered for this small controlled case, and there are only two new target requests with one decode interval each. Therefore SLO attainment, P50/P99 of target TBT, confidence intervals and robust percentile claims are **not measured**. The D0 low-load seed interval (~4.626624 ms) may be used as a descriptive reference only; setting an SLO after seeing the policy outcomes would be post hoc. There is no valid normalized SLO claim in this report.
