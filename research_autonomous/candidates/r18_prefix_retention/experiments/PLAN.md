# Registered minimum experiment: ordinary D eviction threshold

1. Run `run.py --fillers 24` and `--fillers 28`. Both use the same two
   P GPUs, one D GPU, 100-Gb/s source cut, normal3,400-block D pool,
   prefixes, 4.8-s target arrival, and deterministic filler token-ID
   stream. The sole changed factor is the count of ordinary distinct
   fillers. Targets are two different prefixes, so single-flight cannot
   combine them. The extra four fillers are a controlled mechanism input.
2. Analyze each case with `analyze.py`. Assert complete prior work, both
   P hits1,984 tokens, D query2×hit versus2×miss, exact delta/full KV
   bytes, source-cut path, no capacity wait, final-flow→ready→admit→
   token2→completion, and all requests complete. A violation marks the
   run `INVALID` and triggers causal diagnosis, not a positive result.
3. Causal ablation: keep all28 fillers, then issue two ordinary 2,048-token
   refresh requests for the warm keys at4.5 s. They must finish before
   the unchanged4.8-s target arrival. They restore D residency through
   real Prefill/P2D/Decode work; no cache is manually cleared or pinned.
   The target should return to the delta path. A third25/26-filler run
   is permitted only if the query switches partially or the registered
   threshold needs localization.
4. If the phenomenon repeats, label `MOTIVATION_VALIDATED` under the
   user's new definition only for the **conditional cache-state problem**.
   The D-hit control is not algorithmic headroom. Before any solution,
   compare LRU/LFU/cost-aware retention, DELTA, single-flight and
   cache-aware D routing in an online stream with a lawful signal.

Reproduce from repository root with the checked-in simulator environment:

```bash
/home/lpm/.conda/envs/llmsim-flowsim/bin/python research_autonomous/candidates/r18_prefix_retention/experiments/run.py --fillers 24 --tag reproduce
/home/lpm/.conda/envs/llmsim-flowsim/bin/python research_autonomous/candidates/r18_prefix_retention/experiments/run.py --fillers 28 --tag reproduce
/home/lpm/.conda/envs/llmsim-flowsim/bin/python research_autonomous/candidates/r18_prefix_retention/experiments/run.py --fillers 28 --refresh --tag reproduce
/home/lpm/.conda/envs/llmsim-flowsim/bin/python research_autonomous/candidates/r18_prefix_retention/experiments/analyze.py research_autonomous/candidates/r18_prefix_retention/experiments/filler_24_reproduce
/home/lpm/.conda/envs/llmsim-flowsim/bin/python research_autonomous/candidates/r18_prefix_retention/experiments/analyze.py research_autonomous/candidates/r18_prefix_retention/experiments/filler_28_reproduce
/home/lpm/.conda/envs/llmsim-flowsim/bin/python research_autonomous/candidates/r18_prefix_retention/experiments/analyze.py research_autonomous/candidates/r18_prefix_retention/experiments/filler_28_refresh_reproduce
```

Use a fresh alphanumeric tag if `reproduce` already exists. The original
case directories are frozen and cannot be overwritten by the runner.
