# Priority opportunity and oracle headroom

## What the measured policy comparison says

The measured policy comparison in `03_DIRECTION_B_RESULTS.csv` has a clear
class ordering:

```text
KV_FIRST  -> severe recurrent EP collective / seed TBT tail
FAIR      -> small EP CCT tail and <1% mean seed-TBT cost relative to EP_FIRST
EP_FIRST  -> recovers most EP effect with no measured P2D TTFT penalty
```

This is not evidence that a more elaborate arbitration policy beats the
simple static policy. It is evidence that, for this selected point, the
costly choice is giving KV strict precedence. An explicit request-targeted
network-priority replay was not conducted, and the fixture contains only one
independent EP4 group per rail. However, the integrated event ledger permits
two strict serving-level upper bounds for this exact B workload:

- Every candidate's required KV flows finish before the Prefill completion
  callback that triggers `P2D_READY`. The last KV completion leads handoff by
  653.791 us for 2048-token candidates and 793.964 us for 1024-token
  candidates in FAIR; the gap remains positive under EP_FIRST, KV_FIRST and
  EP_ISOLATED. With compute/release times fixed, an offline oracle that only
  gives a candidate's KV more service can move those completions earlier but
  cannot improve TTFT: the request is already waiting for the later Prefill
  completion. The measured-ledger upper bound on TTFT gain is therefore 0
  for these candidates.
- On Decode, EP_FIRST matches EP_ISOLATED on seed TPOT and ITL P99. The
  measured FAIR-to-EP_ISOLATED upper bound is 0.61% in mean TPOT and 0% in
  ITL P99. EP_ISOLATED is a virtual-capacity attribution control, not a
  deployable policy; EP_FIRST already captures this measured cross-class
  opportunity. There is no second independent EP group on the same rail for
  a legal same-class collective oracle to arbitrate.

These are event-ledger/counterfactual upper bounds, not a simulated
request-specific priority policy or SLO oracle. A within-class KV replay
could still redistribute shard FCT and harm another request, but no TTFT/SLO
gain is available in this fixed B workload under its current compute/release
DAG.

## Counterfactuals versus deployable policies

- `FAIR`, `EP_FIRST`, `KV_FIRST`: measured FlowSim fluid-allocation policies.
- `EP_ISOLATED`: a virtual independent-capacity control for cross-class
  attribution; not a physical fabric or scheduler.
- `EP_ONLY`, `KV_ONLY`: not run for this selected policy campaign.
- Same-class EDF/LLF/SRPT/coflow replay: not run; the B request-level TTFT
  upper bound is zero for this fixed workload, and no grounded SLO thresholds
  were supplied.
- Packet-level priority enforcement: not run.

`04_ORACLE_HEADROOM.csv` records this distinction. Since the tested static
EP_FIRST result is already close to the EP-isolated control and has no
visible KV TTFT cost, there is no demonstrated incremental headroom for a
fine-grained request/barrier priority algorithm at this point.

## Decision

**Do not implement an online scheduler based on these results.** A fair next
scientific step, if the project continues, is not a broad algorithm sweep:
it is first to validate the class-priority mechanism in native ns-3 or a
small RDMA testbed, then construct one legal same-class urgency pair only if
the serving DAG shows two simultaneously active jobs with different real
barrier slack. Generic deadline/flow priority is already heavily occupied by
prior work; no novelty claim is established here.
