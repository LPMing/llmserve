# 08 — Final paper direction decision

## Decision

`NO_GO` for the proposed fine-grained request/barrier-aware network-scheduling paper under the tested simulator and workload envelope. This is a research-direction decision, not a claim that the simulator is fully validated or that all real clusters lack contention.

## Why

- Baseline gate is `PARTIALLY_VALIDATED`, not full PASS: FlowSim serving feedback is present, but integrated packet feedback, exact GateRouter A2A, POST_PREFILL, and arbitrary grouped topologies are not.
- Tested KV–KV and KV–EP cases establish that cross-request physical service interaction is representable. They do not establish material serving-level optimization headroom.
- Two independent EP4 groups are now representable in one bounded rectangular layout and do share directed links. However, their matched integrated serving comparison yields only +0.75–0.80% TPOT/TBT and no TTFT change, despite a 1.6–6.4% collective-CCT change. This fails the serving-headroom gate.
- Nuska directly covers inter-request and stage-aware flow scheduling for TTFT; generic request/barrier/priority scheduling is not a defensible new claim.
- No oracle or deployable policy was evaluated.

The bounded independent-group check has now been completed. Do not proceed to Case D, a priority/oracle sweep, or a scheduler prototype: the measured serving effect is below 1%, and the direct prior-art overlap with Nuska plus LLF/coflow remains unresolved. Keep the topology fix and negative result as simulator capability evidence. Reopen only with a new independently grounded physical or serving mechanism that changes the exposure bound, not by scaling concurrency to chase a larger number.

There is no paper title or confirmed CCF C/B contribution at this point. A generic “request-aware network scheduling” title would overstate novelty.
