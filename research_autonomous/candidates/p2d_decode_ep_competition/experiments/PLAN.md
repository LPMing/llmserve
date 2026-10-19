# Minimal falsification experiment

1. Reuse `two_ep4_groups_full.json`, its physical rank map and 200-Gb/s
   topology. Eight 128/32 requests arrive at zero and keep D active. Four
   2048/3 requests arrive at 100 ms; a 24-request extension uses additional
   non-overloading waves at 180, 260 and 340 ms. The latter is a controlled
   diagnostic, not evidence of production frequency. All shapes are within
   the measured profile and token budget 2048.
2. Run identical workload/config/seed under FAIR, EP_FIRST and KV_FIRST.
   Preserve 4P:4D GPU count, TP2/EP4, per-request D destinations and
   source/destination NICs. Add the prior 20-µs phase baseline if a positive
   FAIR effect survives priority.
3. Archive request CSV, per-flow source/destination logical rank, bytes,
   release/start/end, physical path and directed rail, scheduler arrival,
   prefill end, P2D ready, Decode admission, token 2 and completion, plus
   command and source/profile/config SHA-256.
4. Audit exact P2D bytes per new request (201,326,592 B) and directional
   overlap against EP flows. Only then compare token-2/ITL/completion to
   the no-new-wave cohort and priority controls. Stop if the Oracle cut
   effect or strong-baseline increment is below 10%.
