# 01 — TP rank and P2D receiver correctness gate

Status: `PASS_FOR_MINIMAL_TP2_EP2_G0`; this is a correctness result, not a contention result.

## Scope and provenance

- Repository HEAD: `0c0839aff54ec0abb1810dc09cf3d66f06b1b078`; worktree was dirty.
- Cluster: `experiments/pd_kv_ep/configs/small_pd_tp2_to_decode_tp2.json` (SHA-256 `3e12c7577d14cd511430308cd8eba6a79335a5b9402f66f3817c3d6f1d3b9595`). Prefill TP2 resolves to EP2; Decode is TP2/EP2.
- Model config SHA-256: `0736f3bafb95cc658776c92ab34f5f98d8169634a3a36b84892d71448a1f19d3`.
- Profile metadata SHA-256: `e755433ea63a19e9d4a4919f04da412807aa520972dc97df3dfb8908b6a70f96`. RTXPRO6000 / Qwen3-30B-A3B / BF16 contains TP1 and TP2 dense/attention/per-sequence data; MoE data is profiled at TP1 and used as per-rank MoE latency by the simulator.
- Workload: `research_motivation/kv_handoff/workloads/post_prefill_i2048_o8_1req.jsonl` (SHA-256 `c0413559fd64117a674d16c88509970cd3e8f55d2f27b056476a3636408ad6db`): one request, 2,048 input, 8 output, arrival 0.

## Historical TP2/EP1 skew and corrected configuration

The archived `research_motivation/kv_handoff/01_TRANSFER_SEMANTICS.md` reports a 51.216 ms P2D rank-release gap for TP2/EP1. Its source explanation is consistent with `LLMConverter.convert_prefill`: MoE expert rows are assigned by `expert_id % npus_per_group`; with the old EP1/TP2 configuration this did not represent a balanced two-rank MoE execution. The 51.216 ms was compute/rank-mapping skew, not network queueing, and is excluded from the present evidence.

The corrected gate uses TP2/EP2, a legal divisor of the model's 128 experts and the serving config builder's default MoE mapping. No rank timings were manually aligned and no MoE compute rows or bytes were removed.

## Defect found and minimal fix

The Chakra converter already had an explicit actual-Decode destination path (`pd_decode_offset/tp/pp`), but `serving.core.graph_generator.generate_graph()` did not pass the resolved P/D receiver layout. The converter therefore selected legacy shadow ranks. The first post-fix attempt then failed because FlowSim still polled the reserved Prefill shadow ranks and expected their ET files.

The focused repair now:

1. resolves the request's configured Decode pairing (or infers the sole Decode instance); ambiguous multi-Decode routing fails closed;
2. passes Decode global rank offset, TP, and PP into graph conversion and includes them in the graph-cache key;
3. emits empty compatibility ETs for the reserved shadow ranks, while real P2D SEND nodes target actual Decode ranks;
4. makes an actual-receiver Prefill batch completion wait for every real Prefill source-rank graph, not a synthetic receiver rank.
5. calls the existing `mark_batch_graph_start()` at graph submission (idempotently), so `decode_first_batch_start_ns` is no longer silently left unset.

Regression checks: `experiments/pd_kv_ep/scripts/test_pd_decode_receiver_mapping.py` (7 tests), plus `test_pd_request_pairing.py` and `test_pd_decode_capacity_admission.py` (5 tests); all 12 passed. Python compilation passed for the changed modules.

## One-request LAYERWISE evidence

Run ID: `decodeopp-g0-tp2ep2-realreceiver-v2`; complete command and run outputs are in `/tmp/decode-opportunity-g0-fixed-*` (temporary diagnostic artifacts).

- 48 model layers × 2 TP source ranks = 96 P2D flows.
- Per source rank: 48 × 2,097,152 B = 100,663,296 B.
- Total: 201,326,592 B, exactly the model-derived K+V amount for 2,048 tokens.
- Destinations: 48 flows `0→4`, 48 flows `1→5`; no flow targets shadow ranks 2/3.
- Each layer's two rank-release timestamps match; maximum observed inter-rank release skew: 0 ns.
- Last P2D network-flow completion: 45.142387 ms; Prefill graph/serving completion and TTFT: 46.184 ms. The gap is downstream Prefill graph work after the final layerwise KV release, not rank skew.

## One-request POST_PREFILL evidence

Run ID: `decodeopp-g0-tp2ep2-postprefill-realreceiver-v2`; command is reproduced in `02_METRIC_SEMANTICS.md`.

- Exactly 2 P2D flows, `0→4` and `1→5`, each 100,663,296 B; total remains 201,326,592 B.
- Both flows are released at 46.185000 ms, after the converter's final sampler dependency; both finish at 50.213032 ms.
- Prefill batch completion ranks are `[0,1,2,3]`; Decode admission occurs at 50.213032 ms. The shadow ranks are empty compatibility graphs, not data receivers.
- After the batch-start telemetry repair, `decode_first_batch_decision_ns` and `decode_first_batch_start_ns` both equal 50.213032 ms; the Decode graph's first completion is 54.767032 ms.
- No extra KV flow or duplicated bytes were observed.
- With 3 hops at 0.5 μs/hop, the measured 4.028032 ms shard FCT is consistent with 4.026532 ms serialization of 100,663,296 B at 200 Gbps plus 1.5 μs propagation.

The topology has six logical endpoints and two switches; observed source-to-Decode paths were `0→6→7→4` and `1→7→6→5`. This single-request topology does **not** prove that two different requests share one directed bottleneck.

## Gate decision

Compute graph, profile-backed model configuration, model-derived bytes, TP shard conservation, actual Decode destinations, Decode admission, and first/second-token event sequence passed for this minimal configuration. The former TP2/EP1 rank skew is not used. Proceed only to theory and scheduler-opportunity calibration; no multi-request motivation claim is authorized by these runs.

## Addendum — final cross-cut placement and integrated-rank validation (2026-10-12)

The original G0 topology above remains a single-request correctness gate. It is **not** the topology used for the final cross-request experiment. The latter uses `decode_opportunity_2p2d_tp2.json`, `rank_map_2p2d_tp2_cross_cut.json`, and `two_prefill_two_decode_shared_cut_200g.txt` (hashes and exact rank semantics are in `RUN_PROVENANCE.md`).

The final logical-to-physical map deliberately places the two TP ranks of each Decode group on opposite leaves. Prefill 0/1 ranks map to endpoints 0/1 and 4/5; Decode group D0 maps to endpoints 2/8 and D1 to 3/9. P2D shadow receivers alias their paired actual Decode endpoints. Thus each target request has two 100,663,296-byte required shards: one stays within a leaf and one crosses directed link `12->13`. Decode EP traffic uses the same cross-leaf cut in the forward and reverse directions. The P2D/EP common directed bottleneck is therefore present; this was checked against emitted flow paths, not inferred only from topology intent.

The integrated FlowSim group-command repair is also part of the experiment provenance: independent non-DP Decode instances must submit all ranks in their group so the collective is actually networked rather than locally completed by a one-rank graph. Regression coverage is in `experiments/pd_kv_ep/scripts/test_flowsim_group_queue_ownership.py`, `test_flowsim_collective_scope.py`, `test_flowsim_rank_mapping.py`, and this directory's request-first policy tests. The 31-test focused suite passed before final report generation.

The experiment is explicitly limited to TP2/EP2 and the simulator's generated `ALLGATHER`/`REDUCESCATTER` EP realization. It does not validate sparse GateRouter A2A or high-degree MoE EP. See `07_KV_EP_FEEDBACK_ANALYSIS.md` for the effect of this scope restriction.
