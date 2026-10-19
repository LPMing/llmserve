# Transfer semantics audit

## Verdict

**G0: PASS for this controlled POST_PREFILL run, with a Prefill-rank timing caveat.** POST_PREFILL was exercised through the integrated FlowSim serving path and its real completion callback. It was not merely a network-only replay with hand-written release timestamps. The result is valid for the saved code/configuration, but the TP-rank release skew described below limits generalization.

## Source path

- `serving/__main__.py`: CLI accepts `--pd-kv-transfer-mode {LAYERWISE,POST_PREFILL}` and passes it to `generate_trace` for Prefill and Decode graph generation.
- `serving/core/trace_generator.py::_pd_kv_send_bytes` computes model-derived K+V bytes per layer and per Prefill TP rank. The layerwise trace attaches this amount at each KV-producing projection. In POST_PREFILL, `_emit_final_layers` runs first; then the trace emits one `pd_kv_transfer` marker carrying `_pd_kv_send_bytes(...) * num_layers`.
- POST_PREFILL explicitly rejects a partially computed prompt, PP other than 1, and sub-batch interleaving. This avoids labeling a partial/chunked graph as a complete-request transfer.
- `astra-sim/extern/graph_frontend/chakra/src/converter/llm_converter.py::convert_prefill` handles the marker after the local rank's preceding final-layer/sampler compute node. `_emit_pd_kv_sends` creates SEND nodes to actual Decode ranks in explicit P/D mode. Flow completion closes the graph dependency; it is not an out-of-band fixed-start event.
- `serving/core/flowsim_worker.py` returns completion to the frontend. Prefill graph completion then reaches `router.transfer_prefill_request(..., completion_time_ns=...)`, which calls the paired Decode scheduler's `add_decode`. The request records `p2d_kv_ready_time_ns`; Decode admission waits for availability as well as completed handoff.

## Release granularity and barrier

LAYERWISE releases the model-derived K+V shard after each layer's relevant projection. Subsequent Prefill layers do not wait for the previous layer's KV network send in the current modeled DAG. The request still cannot be handed to Decode until the Prefill graph and all required send dependencies complete.

POST_PREFILL emits the complete 48-layer cache once per source TP rank after that rank's complete Prefill graph reaches the final sampler marker. It does not force all source ranks to release simultaneously. The Decode-ready timestamp is determined by completion of the required transfer dependencies, not by the first shard.

For the one-request run, the two 96-MiB rank shards were released at 13.497 ms and 64.713 ms. For the four-request run the same per-request release anchors occur. The 51.216-ms skew is not network queueing: this config uses Prefill TP=2, EP=1, and the trace/converter emits one MoE expert compute row per layer; `convert_prefill` assigns that expert row to one TP-local rank (`expert_id % npus_per_group`) while the other rank does not execute it. Forty-eight profiled 1.0666-ms MoE rows account for 51.1968 ms, within 19.2 us of the observed skew. Treat this as a rank-mapping/modeling limitation of this configuration, not evidence about balanced production TP execution. The network replay preserves these actual release anchors.

## TTFT and token timestamps

The Prefill scheduler marks the first token at Prefill completion. In this mode the Prefill graph is not complete until its child P2D sends complete, so the recorded first visible token and TTFT include the handoff barrier. On these runs, `TTFT = p2d_kv_ready_time_ns = decode_admit_time_ns` because Decode had spare capacity and was admitted immediately.

The Prefill-side sampler emits the first output token. The Decode-side first generated token is therefore output token 2. With output length 8, the CSV stores `second_token_visible_ns`, `ttst_ns`, per-request ITL sequence, and TPOT. Here all seven ITLs equal 2.627088 ms, so TTST, TPOT, and each measured TBT/ITL are 2.627088 ms. `decode_first_batch_start_ns` is -1 in the request CSV and must be reported as not recorded; do not replace it with the eligible/decision timestamp.

The four-request workload has no already-active Decode EP background during P2D. All four requests cross handoff before their first Decode EP dispatch: the first collective starts at 72.818264 ms, 42 us after the common KV-ready/admission time of 72.776264 ms. Its dispatch CCT is 16.099 us and combine CCT is 10.856 us. This is post-handoff EP execution, not concurrent KV+background-EP contention.

## Accounting checks

- Qwen3 model: 48 layers, 4 KV heads, head dimension 128; BF16 K+V = `2 * 4 * 128 * 2 * 48 = 98,304 bytes/token`.
- 2,048-token request = 201,326,592 bytes total; TP2 gives two 100,663,296-byte shards.
- Both shards are physically sent to the paired Decode ranks; the request-ready barrier waits for both.
- The 1-request integrated trace contains two nonzero P2D flows, not 96 layerwise flows. The 4-request trace contains eight nonzero P2D flows.
- The first oversized 1-request telemetry artifact and its associated early CSV are INVALID: it used an incorrect per-layer/full-cache byte accounting and generated excessive detail. It is quarantined by provenance and excluded from every result here; it has not been deleted.

## Gate record

| Check | Status | Evidence |
|---|---|---|
| POST_PREFILL after complete Prefill graph | PASS | trace marker placement and converter dependency |
| Integrated network-completion feedback | PASS | P2D flow completion → Prefill graph completion → router → Decode scheduler |
| 1-request barrier/lifecycle | PASS | corrected v2 run; two model-derived shards; TTFT equals final required completion |
| Output≥8 second-token accounting | PASS | request CSV includes second token and seven ITLs |
| Atomic all-rank release | NOT ASSUMED | actual source-rank anchors differ by 51.216 ms |
| Active Decode EP overlap | NOT PRESENT in 4-request run | EP begins 42 us after last P2D-ready |
| Balanced Prefill TP rank behavior | NOT VALIDATED | EP1/TP2 trace mapping causes MoE compute skew |
