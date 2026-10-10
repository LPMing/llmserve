# Joint 2x2 oracle results

Status: NOT RUN. The required gate is one natural, capacity-calibrated window
with verifiable barrier exposure. Retained Azure Code prefixes and Azure
Conversation 7421/06210 prefixes have no request whose last KV completion
crosses Prefill completion. The Azure Conversation 06210 run additionally
joins all 73,632 EP collectives to 767 serving Decode batches, but only 1.783%
of critical peer routes are coactive with KV on a shared directed FlowSim
link, with no counterfactual causal delay. No candidate is both
capacity-calibrated and barrier-exposed, so running the 2x2 now would compare
oracles on an unvalidated state and risk manufacturing a joint-scheduling
result.

| Cell | Serving scheduler | Network service | Result |
|---|---|---|---|
| BASELINE | Default | FAIR | Pending candidate window |
| NETWORK_ONLY | Default | Barrier-aware offline oracle | Pending candidate window |
| SYSTEM_ONLY | Legal offline system oracle | FAIR | Pending candidate window |
| JOINT | Legal offline system oracle | Barrier-aware network oracle | Pending candidate window |

All four cells must use the same request IDs, arrivals, token counts, model,
topology, bytes, and routing. Oracle cells may use future information only as
an explicitly labeled upper bound. No gain or synergy is currently claimed.
