# 02 — Minimal model-derived motivation cases

The KV–KV and KV–EP cases use the dirty audited worktree, Qwen3-30B-A3B, profile-backed compute, model-derived KV sizes, TP2/EP16, LAYERWISE P2D, and 200-Gbps scale-out endpoints. The new EP–EP case uses two separate TP2/EP4 groups with the same model and physical link rate. FlowSim is analytical max-min fluid service. The controlled phases are mechanism characterization, not natural production arrivals. `*_ISOLATED` is an independent virtual-link-capacity counterfactual, not a deployable policy.

| Case | Minimal setup | Matched control | Observation | Status |
|---|---|---|---|---|
| A: KV–KV unequal | Two requests, 32 and 128 input tokens, both arrive at 0; separate Prefill instances share P2D cut; 96 layer×TP shards each | Each request alone at same absolute arrival | Small shard FCT changes; request KV-ready/TTFT unchanged | Network interaction; no serving opportunity shown |
| A size-skew boundary | 128+2,048 and 128+8,192 input tokens at 0 | One-request controls | Short-request shard P99 +25.35%, but last shard/ready/TTFT unchanged | Flow-tail amplification only |
| B: EP–EP, 2 requests/group | Two independent Decode EP4 groups across D0/D1; input128/output32, all arrive at 0 | One group only with same two-request group load | Shared directed links active; dispatch CCT +6.39%, combine +1.58%; TTFT unchanged, TPOT/TBT +0.75% | Capability PASS; weak serving effect, motivation NO-GO |
| B: EP–EP, 4 requests/group | Same topology/model; input128/output32, all arrive at 0 | One group only with same four-request group load | Dispatch CCT +6.39%, combine +3.11%; TTFT unchanged, TPOT/TBT +0.80% | Adjacent controlled point; weak serving effect |
| C: KV–EP | Four Decode requests input1/output8 at 0; one input8192/output1 P2D request at 13.396596 ms, after an observed Decode epoch | Same DAG with KV on independent virtual directed-link copies | Same-directed-link overlap; EP CCT P99 +1.08%; TTFT/KV-ready unchanged; TPOT <0.01% delta after wake fix | Weak serving exposure, no motivation PASS |
| Negative phase control | Two-request phase-targeted cases with no interval intersection on shared links | Matched lifecycle controls | No network attribution; a former large TBT gap was a scheduler wakeup bug | Retired as positive evidence |

No Case D multi-request priority experiment was run. Since no case demonstrates meaningful serving-level optimization headroom, FAIR/KV_FIRST/EP_FIRST, EDF/LLF, coflow, and oracle sweeps remain gated. No per-request splitting of an aggregate Decode collective was performed. The EP–EP case uses two actual independent group collectives and retains request-ID sets on each grouped collective event.

## Telemetry semantics

The ledgers retain request, layer/shard or collective, source/destination rank, release/start/finish, bytes and directed route. An EP collective is a group barrier over required peers, not a single P2P FCT. Request KV-ready is the maximum finish over required shards. FlowSim `queue_bytes` is residual fluid backlog, not packet/switch buffer occupancy. Native ns-3 results are network-only fixed-issue-time replays and do not feed completion into serving.

## Retired observations

Pre-Chakra-unit-fix latencies and phase alignments are invalid. TBT values generated while the worker slept behind stale future-arrival suppression are also retired. Only post-fix values in the reproducibility ledger may be used.

For EP–EP, 1,488 deterministic collective rounds per group and phase had the
same CCT at a given operating point. Thus mean and P99 coincide in these runs;
the repeated within-run rounds are not independent request-tail samples. Full
commands and gate interpretation are in
[`12_EP_EP_GROUP_VALIDATION.md`](12_EP_EP_GROUP_VALIDATION.md).
