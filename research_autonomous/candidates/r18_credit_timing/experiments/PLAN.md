# Registered minimum experiment: early D credit threshold

1. Run `run.py --prompt-tokens 12000` as the negative control and
   `--prompt-tokens 14000` as the capacity threshold. Four requests,
   four P GPUs, one D GPU, normal3,400-block pool and declared100-Gb/s
   cut stay fixed. Each request generates64 tokens. Only prompt length
   changes, and the profile supports both context lengths without
   extrapolation.
2. The formula predicts four12k credits need3,004 blocks and start at
   t=0; four14k credits need3,504, so the fourth P sees only772 free
   blocks and waits while D has no ready request. Record credit hold,
   P idle, D ready/admit, Decode queue time, final flow, token2 and
   completion. The analyzer checks all flow bytes/path,4 completions,
   block bounds and event order.
3. This validates or falsifies the *current early-credit protocol's*
   resource-idling mechanism. It does not establish production-system
   prevalence or an achieved JIT gain. A future causal ablation must
   implement source KV retention and delayed receiver credit without
   sending any bytes before credit. Then compare two-stage FIFO, SRPT,
   EDF and tuned P:D ratio on heterogeneous arrivals/deadlines.

```bash
/home/lpm/.conda/envs/llmsim-flowsim/bin/python research_autonomous/candidates/r18_credit_timing/experiments/run.py --prompt-tokens 12000 --tag reproduce
/home/lpm/.conda/envs/llmsim-flowsim/bin/python research_autonomous/candidates/r18_credit_timing/experiments/run.py --prompt-tokens 14000 --tag reproduce
/home/lpm/.conda/envs/llmsim-flowsim/bin/python research_autonomous/candidates/r18_credit_timing/experiments/analyze.py research_autonomous/candidates/r18_credit_timing/experiments/prompt_12000_reproduce
/home/lpm/.conda/envs/llmsim-flowsim/bin/python research_autonomous/candidates/r18_credit_timing/experiments/analyze.py research_autonomous/candidates/r18_credit_timing/experiments/prompt_14000_reproduce
```

Use a fresh alphanumeric tag if `reproduce` already exists. Frozen
original case directories are never overwritten.

## Round 19 matched admission and network-order checks

Hold the four P GPUs, one D GPU, 3,400 D blocks, 100-Gb/s source cut,
profile, full-KV POST_PREFILL transfer and request stream fixed. Compare
EARLY versus TWO_STAGE_FIFO, first for four 14k/64 jobs at zero and then
for `(12k,32,0)`, `(14k,96,0.2s)`, `(14k,48,0.4s)`,
`(16k,64,0.6s)`. The latter has real arrival and Decode-work ordering;
no future information is used by FIFO. The separately registered
`KV_REQUEST_FIRST id0` case characterizes a lawful equal-arrival FIFO
tie-break only in the uniform stream. It is not a general online policy.

The analyzer requires exact model bytes, four completions, receiver credit
before first flow, live source KV through last flow, no more than 3,400
reserved D blocks and `last_flow <= ready <= admit <= token2 <= completion`.
The conditional admission Oracle holds FlowSim FAIR and FIFO Decode fixed.
It excludes network ordering, rebatching, role changes and future routing.
`TTFT` is a Prefill-graph completion proxy; its location differs across
these two trace forms, so the matched outcomes are P2D-ready, token 2 and
modeled request completion.

Additionally replay `EARLY_LAYERWISE` with the same resources and both
streams. It overlaps P2D with Prefill and is a stronger practical early
protocol. It has the same total bytes but a different transfer DAG, so
the POST pair remains the clean admission-timing ablation and the
layerwise pair is a whole-protocol strong-baseline comparison.

```bash
/home/lpm/.conda/envs/llmsim-flowsim/bin/python research_autonomous/candidates/r18_credit_timing/experiments/run.py --prompt-tokens 14000 --admission EARLY_POST --tag fresh1
/home/lpm/.conda/envs/llmsim-flowsim/bin/python research_autonomous/candidates/r18_credit_timing/experiments/run.py --prompt-tokens 14000 --admission TWO_STAGE_FIFO --tag fresh2
/home/lpm/.conda/envs/llmsim-flowsim/bin/python research_autonomous/candidates/r18_credit_timing/experiments/analyze_matched.py research_autonomous/candidates/r18_credit_timing/experiments/prompt_14000_two_stage_fifo_fresh2
/home/lpm/.conda/envs/llmsim-flowsim/bin/python research_autonomous/candidates/r18_credit_timing/theory/admission_oracle.py
```

The completed Round-19 cases use unique `r19a`, `r19b`, `r19h` and
`r19prio` suffixes; their manifests preserve exact commands and hashes.
