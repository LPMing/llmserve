# Research gates after Round 19

The gates describe different claims. A simulated causal mechanism can
pass the motivation gate without proving an algorithm or paper result.

| Gate | Required evidence | Current result |
|---|---|---|
| `MOTIVATION_VALIDATED` | Profile/model-derived trigger, negative control, threshold case, causal ablation, deployment explanation, audited Serving event chain | **Passed for A:** normal D eviction turns two P-prefix hits into full-KV P2D; ordinary refresh restores deltas. Frozen report: [MOTIVATION_REPORT.md](MOTIVATION_REPORT.md). |
| `PAPER_HEADROOM_VALIDATED` | Same requests, GPU/NIC/KV pool and cache initial state; implementable strong baselines; legal Oracle; measured end-to-end gap | **Open.** Round-19 A history/cost case is solved on modeled target completion by plain LFU. Round-19 B is solved on admission timing by two-stage FIFO within 0.000252%/zero of its scoped Oracle. C's simple network-order control gains only 6.76% over FAIR. |
| `SOLUTION_VALIDATED` | Executable mechanism beats the strongest simple comparator with correctness and causal ablation | **Open.** No new policy implementation or gain is claimed. |
| `PAPER_READY` | External workload validity, broad baselines, robustness, limitations and reproducible artifact | **Open.** No large trace result is claimed. |

## Candidate evidence and next tests

| Line | Theory trigger | Direct observation | Next falsifier |
|---|---|---|---|
| A: P/D KV residency inversion | D 3,400 blocks; frozen 24/28-filler state gap and ordinary refresh | Frozen targets complete 56.971 vs 79.029 ms. Round-19 legal history/varied-cost 34-request comparison gives LRU 79.029 ms and simple LFU 56.971 ms; LFU's residual 10.486-MB transfer is hidden under Prefill. | Current fixture `NO_GO` for paper headroom. Require an observed online signal and >10% gap after LFU, cost-aware, DELTA, single-flight and D routing. |
| B: early Decode credit timing | Four 14k credits use 3,504 > 3,400 blocks, while source P pools can hold Prefill output | Correct two-stage FIFO improves last completion 25.35%/22.56% vs matched early POST and 17.92%/18.07% vs stronger early LAYERWISE; scoped admission-only Oracle gaps 0.000252%/zero. | Current admission-timing fixture `NO_GO`; use two-stage FIFO and early layerwise as strong protocol baselines. |
| C: joint bottleneck switch | Three simultaneous transfer credits share a 100-Gb/s cut and delay fourth D credit | Same-resource FIFO-tie-break network priority reduces last completion 4.8423→4.5150 s, 6.76%. An unchanged first-50 Llama ShareGPT screen gives 0.492-s full-KV cut work and at least11.766-s last-request Decode work after arrival; 3.078% fixed-work ratio is not a global joint bound. | Current uniform and network-only cases `NO_GO`; find a lawful online joint memory/Decode-order failure after simple policies, then a same-resource Oracle. |

The A analytic decision screen is
[`candidates/r18_prefix_retention/theory/online_baseline_screen.json`](candidates/r18_prefix_retention/theory/online_baseline_screen.json).
The B bound is
[`candidates/r18_credit_timing/theory/optimistic_jit_bound.json`](candidates/r18_credit_timing/theory/optimistic_jit_bound.json).
Neither JSON is a Serving performance measurement.

Round-19 measured admissions and their scoped Oracle are in
[`candidates/r18_credit_timing/theory/admission_oracle.json`](candidates/r18_credit_timing/theory/admission_oracle.json).
The full source, bytes and timeline checks are in each case's
`matched_analysis.json` or `history_analysis.json`.
