# 04 — Novelty audit and gate

## Candidate claim

Fine-grained scheduling across Request/Batch/Collective barriers in PD-MoE serving may be useful because KV and Decode communication can share physical resources. This statement alone is not novel: network sharing, flow priority, deadline/laxity, coflow barriers, dependent coflow DAGs, request/batch arbitration, and finite queues all have substantial prior art; Nuska directly addresses stage-aware inter-request LLM serving communication for TTFT.

## What would count as a technical difference

A candidate would need to prove a decision divergence, not a terminology difference. Required proof:

1. Give an executable, legal multi-request communication DAG with genuine shared directed resources.
2. Show a case where a flow-level EDF/SRPT/LLF rule and a collective/coflow barrier rule choose differently.
3. Show Nuska's documented stage/RLI/RED/defer-promote logic, applied to the same available state, does not make the useful decision; do not compare against a strawman.
4. Quantify an offline schedule upper bound and a finite-priority/host-scheduling realization under equal bytes, releases, routes, and compute.
5. Show TTFT/TBT/SLO improvement, fairness, and starvation cost.

## Current status

| Gate | Result | Reason |
|---|---|---|
| Request/barrier identity is present in instrumentation | PARTIAL PASS | Request, layer, group collective and rank provenance exist in FlowSim; packet replay carries message provenance but is not serving-integrated. |
| KV–KV serving motivation | NO-GO in tested points | Shard tails move (up to +25.35% P99) but the last required shard/KV-ready/TTFT does not. |
| KV–EP serving motivation | NO-GO in tested point | Same-link interval overlap exists, but EP CCT P99 +1.08%, TTFT unchanged, TPOT <0.01%. |
| EP–EP independent-group motivation | Capability PASS / serving-headroom NO-GO | Two groups share directed links; CCT changes +1.6–6.4%, but TPOT/TBT <1% and TTFT unchanged. |
| Difference from Nuska/LLF/coflow | NOT PASSED | No minimal counterexample or decision divergence has been demonstrated. |
| Practical finite-queue implementation | NOT RUN | No algorithm/oracle work is authorized before motivation and novelty pass. |

**Verdict: `NOVELTY_NOT_ESTABLISHED`; research decision: `NO_GO` for this candidate.** Do not call a request-aware priority formula a contribution. The bounded Decode-group case is now represented faithfully enough to test its serving effect, but that effect is under 1% on TPOT/TBT. A broader novelty audit or head-to-head baseline is not justified absent serving-level motivation. The present evidence does not support a CCF C/B paper claim.
