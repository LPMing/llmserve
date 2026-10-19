# 02 — Token, handoff, and latency metric semantics

## Source-defined meanings

The relevant implementation is `serving/core/scheduler.py::add_done()` and `serving/core/request.py`:

| Quantity | Current source / meaning |
|---|---|
| Prefill sampler completion | Not a named Request field. In `POST_PREFILL`, the transfer marker is appended after `_emit_final_layers()` (including `lm_head` and `sampler`) and its SEND depends on the preceding sampler compute node. Thus the first P2D `requested_start_ns` is an exact sampler-completion boundary for this mode. |
| Earliest/theoretical first-token availability | For the current POST_PREFILL DAG, it can be reported as the sampler boundary above, but the simulator does not independently record a user-output callback there. Treat as a derived diagnostic, not the current TTFT. |
| `TTFT` / `first_token_visible_ns` | Set by Prefill `add_done()` at the Prefill graph completion callback. In this graph the callback waits for required P2D SEND completion; therefore the reported TTFT includes full P2D handoff. `first_token_visible_ns` currently aliases that reported time and must not be interpreted as sampler time. |
| Last required KV finish | Maximum end timestamp over all required P2D flows/shards for the request. |
| `p2d_kv_ready_time_ns` | Timestamp when the Prefill graph completion callback transfers the request to Decode. It is after all sender-rank graph requirements; in the tested path it equals the last P2D finish plus any remaining graph dependency time. |
| Decode eligible / admission | `decode_eligible_time_ns` and `decode_admit_time_ns` are set when `DecodeScheduler.add_decode()` can put the request into its running set. They can exceed KV-ready if capacity is unavailable. |
| First Decode batch | `decode_first_batch_id` and `decode_first_batch_decision_ns` are populated at scheduler selection. A telemetry bug left `decode_first_batch_start_ns=-1`; it is now recorded idempotently when the graph is submitted to the backend. This is submission/execution start in the cycle-level event model, not a measured GPU kernel start. `decode_first_batch_finish_ns` is available at batch completion. |
| Second token | `second_token_visible_ns` is set on the Decode batch that produces token index 2. |
| `TTST` | `second_token_visible_ns - (arrival + reported TTFT)`, i.e. second-token time after the simulator's reported first-token time. |
| Arrival-to-second-token | `second_token_visible_ns - arrival`; distinct from TTST when the theoretical Prefill token predates P2D completion. |
| TPOT / ITL | TPOT is request latency minus reported TTFT divided by output tokens after the first; ITLs are timestamp differences from `recent_end`, initialized by reported TTFT. |
| Request completion | `end_time` / `latency` when generated output reaches the configured output length. |

## POST_PREFILL one-request event ledger

Run: `decodeopp-g0-tp2ep2-postprefill-realreceiver-v2`; request output CSV `/tmp/decode-opportunity-g0-postprefill-requests.csv`, KV flows `/tmp/decode-opportunity-g0-postprefill-flows.jsonl`, serving event ledger `/tmp/decode-opportunity-g0-postprefill-serving.jsonl`.

| Event | Time |
|---|---:|
| Arrival / Prefill start | 0 ns |
| Sampler-completion boundary (first P2D release) | 46,185,000 ns |
| Both P2D shard finishes | 50,213,032 ns |
| Prefill batch completion / reported TTFT / first-token field | 50,213,032 ns |
| P2D ready / Decode eligible / Decode admission / first batch decision | 50,213,032 ns |
| First Decode batch decision / graph submission | 50,213,032 ns |
| First Decode batch finish / second token visible | 54,767,032 ns |
| Reported TTST | 4,554,000 ns |
| Arrival-to-second-token | 54,767,032 ns |
| Request completion | 82,091,032 ns |

This is not evidence that a real deployment exposes the first output token at 46.185 ms: it is the earliest token-available boundary implied by the sampler dependency. The current simulator's user-facing TTFT is 50.213032 ms because it records visibility only after P2D is drained. Future comparisons must report both `sampler_boundary_ns` and `ttft_reported_ns`; never relabel one as the other.

The network handoff adds 4.028032 ms after sampler completion in this POST_PREFILL gate. Consequently, reported TTST (4.554 ms) is not the same as a hypothetical sampler-to-second-token interval (8.582032 ms). We do not change existing metric definitions in this phase.

## Cross-request study metric guardrail

The later two-lane experiment preserves these distinctions. In its `POST_PREFILL` runs, P2D release time is used as the exact sampler-completion **dependency boundary** for analysis, but is not a client callback. `ttft_reported_ns` remains the existing simulator field and is P2D-ready in this path. The following outputs are kept separate in `06_SERVING_INTEGRATED_RESULTS.csv`:

- `reported_ttst_ns`: second-token timestamp minus the simulator's reported TTFT;
- `sampler_to_second_diagnostic_ns`: second-token timestamp minus the P2D release/sampler boundary;
- `arrival_to_second_ns`: second-token timestamp minus request arrival;
- `request_completion_ns`: completion timestamp for the two-output-token target, which coincides with its second-token timestamp in this workload.

For target request 3, FAIR has `reported TTST=4.710500 ms`, while the offline decode-opportunity control has `5.368109 ms` (worse by 0.658 ms). At the same time, the sampler-boundary diagnostic falls from `12.799067 ms` to `9.418200 ms`, and arrival-to-second falls from `83.676884 ms` to `80.296017 ms`. This apparent disagreement is not a contradiction: the policy moves the simulator's reported first-token/TTFT anchor earlier with P2D readiness, while the diagnostic sampler boundary is earlier still. Because the simulator has no independent client-token callback at sampler completion, the sampler-boundary result is a causal diagnostic, not yet a production-valid TTST measurement. We therefore claim only a changed modeled second-token/request-completion event, not a validated user-visible TTST or SLO gain.

Each target emits only one inter-token interval (`output_tokens=2`); its “TBT” is one observed interval, not a distribution. Do not report target TBT P50/P99. The longer active Decode seeds provide repeated iteration intervals, but those are controls, not samples of the newly admitted target requests.

## Data completeness / open instrumentation

- The tested POST_PREFILL marker gives an exact sampler boundary indirectly through its causal release. No general `prefill_sampler_ns` Request field exists yet.
- `decode_first_batch_start_ns` was initially missing; it is now populated at graph submission and verified in run `decodeopp-g0-tp2ep2-postprefill-starttime-v3`. This is an event-model graph-submission boundary, not GPU hardware start telemetry.
- This one-request run has no request-level latency distribution; no P50/P99 claim is meaningful from one sample.
- The 7 ITL values are all 4.554 ms in this deterministic single-request run; this is a correctness check only.

## Reproduction command

```bash
SERVING_BATCH_MISS_EVENT_LOG=/tmp/decode-opportunity-g0-postprefill-serving.jsonl \
PYTHONPATH=/home/dell/lpm/LLMServingSim/astra-sim/extern/graph_frontend \
PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python \
/home/lpm/.conda/envs/llmsim-flowsim/bin/python -m serving \
  --cluster-config experiments/pd_kv_ep/configs/small_pd_tp2_to_decode_tp2.json \
  --dataset research_motivation/kv_handoff/workloads/post_prefill_i2048_o8_1req.jsonl \
  --network-backend flowsim \
  --flowsim-topology experiments/pd_kv_ep/configs/ns3/two_prefill_6_rank_shared_spine.txt \
  --flowsim-rank-map research_motivation/decode_opportunity/rank_map_tp2.json \
  --flowsim-policy FAIR --request-routing-policy RR \
  --pd-kv-transfer-mode POST_PREFILL --dtype bfloat16 \
  --max-num-seqs 8 --log-interval 1000 \
  --flowsim-telemetry /tmp/decode-opportunity-g0-postprefill-flows.jsonl \
  --output /tmp/decode-opportunity-g0-postprefill-requests.csv \
  --run-id decodeopp-g0-tp2ep2-postprefill-realreceiver-v2
```
