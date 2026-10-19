# Independent reference scheduler tests

Command:

```text
/home/lpm/.conda/envs/llmsim-flowsim/bin/python research_new_mainline/reference_owner_scheduler.py
```

Observed:

```text
case,dispatch_ticks,compute_ticks,combine_ticks,lower_bound,exact_streaming,bulk,ideal_gap
cross_owner_positive_toy,6;2,1;6,2;5,13,15,21,6
single_owner_dominant_negative_toy,8;1,6;1,4;1,18,18,20,2
symmetric_negative_toy,3;3,4;4;2,9,12,14,2
```

The scheduler asserts each exact optimum is no lower than its analytical lower bound and no slower than bulk. `cross_owner_positive_toy` has 6 ticks of exact ideal improvement; the near-negative has 2. The name `symmetric_negative_toy` means no owner-specific ordering distinction, not zero ordinary pipelining gain.

These fixtures intentionally use abstract ticks and zero startup/propagation/launch cost. They are unit/proof cases only and must not appear in Qwen model results or motivation plots.

