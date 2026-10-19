# H2 theory: request-level KV urgency and masking

## Readiness equation

For a request whose Decode admission waits for both Prefill completion and all required KV transfers:

`t_ready = max(t_prefill_done, t_last_required_kv)`

Define the observed compute-masking slack:

`slack = t_prefill_done - t_last_required_kv`.

If a counterfactual only delays the last required KV completion by `δ`, with the same Prefill schedule and no other event changes, then:

`Δt_ready = max(0, δ - slack)`.

This equation does not sum shard FCTs. It explicitly models the last-required shard and the max barrier. It also does not say that any observed per-shard P99 is a valid `δ` for the last shard.

## Observed request classes

| Existing fixture/request | Last-KV → ready slack | Extra last-KV delay 0.5 / 0.7 / 1.0 / 1.5 ms | Observed consequence |
|---|---:|---|---|
| 128-token small victim, +2,048 background | 1.093557 ms | 0 / 0 / 0 / 0.406443 ms ready shift | Actual last KV is 41.957443 ms, ready is 43.051 ms; no observed ready/TTFT shift |
| 2,048-token background request | 1.418913 ms | 0 / 0 / 0 / 0.081087 ms | Actual last KV is 63.293087 ms, ready is 64.712 ms |
| 8,192-token background request | 1.795913 ms | 0 / 0 / 0 / 0 | Actual last KV is 293.532087 ms, ready is 295.328 ms |
| A7 FAIR, 1,024-token candidate | 0.793964 ms | 0 / 0 / 0.206036 / 0.706036 ms | Next recorded Decode batch decision is 1.706891 ms after baseline ready |
| A7 FAIR, 2,048-token candidate | 0.653791 ms | 0 / 0.046209 / 0.346209 / 0.846209 ms | Next recorded Decode batch decision is 3.531673 ms after baseline ready |

The detailed arithmetic rows are in [`08_KV_REQUEST_RESULTS.csv`](08_KV_REQUEST_RESULTS.csv). Hypothetical delays are not observed, are not generated from a shard percentile, and do not include network/scheduler feedback.

## Interpretation

The 128-token request does have worse within-request shard FCT distribution under large KV background (mean +10.91%, shard nearest-rank P99 +25.35% in the historical 128+2,048/8,192 comparisons). That effect remains outside its request barrier: its last required KV still finishes 1.094 ms before the readiness timestamp. The A7 candidates also finish their last KV 0.654–0.794 ms before the handoff readiness point.

For the A7 records, even adding 1.5 ms to the last KV would move arithmetic `p2d_ready` by at most 0.846 ms. That remains before the *recorded baseline* next Decode decision by 1.707 ms (1,024 prompt) or 3.532 ms (2,048 prompt). This suggests the tested delays do not cross the fixture's next recorded admission decision. Since this is arithmetic against a frozen baseline timestamp, it is not a simulated claim about what a delayed request would do to subsequent scheduler wakeups.

No evidence shows a KV request whose fairness-induced last-required-KV delay advances or postpones Decode admission/TTST. TTFT equals the Prefill/handoff readiness timestamp in the one-token candidates, but their KV completes earlier; therefore the compute callback remains the critical predecessor. TTST is separately defined as second-visible-token minus first-visible-token, but the fixture's `output_tokens_field=1` makes those TTST values diagnostic only.

**H2 verdict: `KV_NETWORK_EFFECT_MASKED` in the tested layerwise serving DAG.** There is within-KV network interference at shard level, but the observed last-shard delays are masked by Prefill compute and the tested admission cadence. Do not continue by enlarging prompts or delaying arrivals solely to consume the measured slack.
