# Fork-group replication degree

**Scenario/data.** One Qwen3-30B-A3B TP2 Prefill fans a 4105-token
BF16 shared prompt to four equal Decode branches (C hypothetical fork).
The model-derived KV is403,537,920 B total, 201,768,960 B/TP rank (A).
Two 200-Gb/s rails need8.071 ms per copy on the source cut; `k` copies
need at least `k×8.071` ms if the source rails are shared. Compute/transfer
overlap and branch completion are unsupported in the current router, so the
screen uses the existing measured D step proxies and states its assumption.

The weak all-on-one-D comparator suggests18.66% for four copies at one
point, but the strong baseline envelope of one D and equal four D already
matches or nearly matches the Oracle over output lengths1–64. Exact
enumeration gives `Gain_upper≤3.45%` with a hot-P proxy and≤1.18% with
full Prefill. The critical path includes copy service plus the slowest
branch's Decode steps; a single network FCT is not a group response.
Status `NO_GO` for symmetric branches. A heterogeneous real fork would
need an observed branch group, marginal-cost greedy, cache-sharing and
source ownership before a new test. Existing enumeration:
`research_branch_group/theory_gate.py`.
