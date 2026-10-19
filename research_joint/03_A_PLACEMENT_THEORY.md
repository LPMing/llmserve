# Direction A — Placement/admission theory and gate

## Candidate objective

With fixed resources, route a newly prefilling request to a legal Decode group based on both the time its complete required KV becomes available and the group's actual admission opportunity. For candidate `d`:

`T_start(d) ≥ max(T_last_KV(d), T_decode_slot(d), T_group_eligible(d))`

The first two terms are only a lower bound. Scheduler epoch, active sequence cap, KV capacity, DP group synchronization, and EP iteration barriers can further delay execution. A valid comparison would preserve the same requests, bytes, GPU/NIC resources, and complete TP receiver mapping across every placement.

## What previous evidence already says

The repository's bounded Decode-opportunity study is the closest serving example. In one controlled two-lane case, one target's network completion crossed a real slot boundary: second-token/request-completion advanced by 3.381 ms. But the other lane stayed busy much longer; pair makespan improved only 43.5 µs (~0.014%). In the 13-token seed neighbor, the target gain collapsed to about 43 µs. It is therefore a narrow opportunity-boundary observation, not aggregate goodput evidence.

Separately, the old P/D placement/path oracle changed network completion by only 0–7.1% in the selected windows and was not integrated into serving. A 3-candidate configuration could be built with fixed total resources, but it would not address the main blocker by itself.

## Why not run another 3-candidate sweep now

The selection rule `min_d max(network readiness, serving/load availability)` is exactly the class of network-cost plus load/cache-aware Decode choice that NetKV studies. DistServe/Mooncake already make P/D placement and load/transfer cost part of serving architecture; ELDR adds MoE-specific Decode routing state. No distinct candidate-specific signal, fairness objective, or joint interaction absent from those policies has been identified here. The mission requires a non-trivial difference from a single-side optimizer, not merely showing the `max()` decision works.

No fixed-resource S0–S3 experiment comparing a network-only, serving-only, and joint placement was run. Treating the prior two-lane opportunity case as that comparison would be incorrect.

## Gate result

`A_PLACEMENT_NO_INCREMENTAL_HEADROOM` for a new paper line. The timing mechanism can happen; the available evidence says its global benefit can be tiny, and the obvious joint selection rule is directly overlapped by existing network-aware Decode selection. Reopen only for a concrete, measurable factor that makes a distinct algorithm decide differently from NetKV/load-aware scheduling; do not enlarge the current fixture just to produce a larger point estimate.
