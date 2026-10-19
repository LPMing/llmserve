# Final research audit — executive summary

## Decisions

- Old mainline: **`FINAL_KV_EP_FLOW_SCHEDULING_NO_GO`** for the tested Qwen3
  configurations and serving/network envelope. Controlled cases can show large
  EP protection, but natural KV handoffs retain Prefill slack, natural policy
  deltas are near zero, and novelty against stage-aware scheduling is not
  established. This is not a universal claim that KV and EP never contend.
- Forced next candidate: **Sparse MoE A2A traffic geometry / collective-tail
  exposure** was screened once. Result: **`SPARSE_A2A_MODEL_NOT_VALIDATED`**.
  Its same-byte counterfactual rewrites destination assignments, coalesces 48
  layers into a phase, and has no serving feedback. Do not call the observed
  approximate CCT gap a legitimate optimization opportunity.
- No scheduler, placement algorithm, or packet experiment is authorized by
  these results. The candidate can resume only after route/expert and
  per-layer/per-round barrier semantics are corrected.

## Read in this order

1. [`01_EVIDENCE_LEDGER.md`](01_EVIDENCE_LEDGER.md) — frozen results and provenance.
2. [`02_CRITICAL_PATH_HEADROOM.md`](02_CRITICAL_PATH_HEADROOM.md) and
   [`03_NATURAL_WORKLOAD_EXPOSURE.md`](03_NATURAL_WORKLOAD_EXPOSURE.md) —
   serving-barrier and natural-trace evidence.
3. [`06_KV_EP_FINAL_GO_NO_GO.md`](06_KV_EP_FINAL_GO_NO_GO.md) — old-line decision.
4. [`09_SPARSE_A2A_MINIMAL_MOTIVATION.md`](09_SPARSE_A2A_MINIMAL_MOTIVATION.md)
   and [`11_NEW_MAINLINE_GO_NO_GO.md`](11_NEW_MAINLINE_GO_NO_GO.md) — bounded
   new-line screen and decision.
5. [`10_RELATED_WORK_COMPETITION.md`](10_RELATED_WORK_COMPETITION.md) — closest
   prior work and novelty risk.
6. [`12_REPRODUCIBILITY_AND_HASHES.md`](12_REPRODUCIBILITY_AND_HASHES.md) —
   commands, hashes, tests and validity limits.

The per-request and per-collective CSVs are audit ledgers, not pooled
percentile summaries across unrelated experiments. `NOT_RUN` means unmeasured,
not zero.

