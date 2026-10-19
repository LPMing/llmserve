# Run provenance and reproducibility record

## Repository state

- Repository: `/home/dell/lpm/LLMServingSim`
- Git HEAD at audit: `0c0839aff54ec0abb1810dc09cf3d66f06b1b078`
- ASTRA-Sim path resolves within this checkout; its reported HEAD is the same SHA.
- Worktree is dirty. Existing modifications/untracked artifacts belong to the ongoing research workspace and were preserved. Relevant modified source includes `serving/__main__.py`, `serving/core/trace_generator.py`, and the existing serving/FlowSim stack; relevant untracked items include the rank-mapped config/topology, the two workloads, and the replay analysis script. No cleanup or rollback was performed.
- Complete `git status --short` snapshot at audit time:

      M experiments/pd_kv_ep/scripts/test_pd_decode_capacity_admission.py
      M serving/__main__.py
      M serving/core/config_builder.py
      M serving/core/controller.py
      M serving/core/flowsim_backend.py
      M serving/core/flowsim_worker.py
      M serving/core/graph_generator.py
      M serving/core/request.py
      M serving/core/router.py
      M serving/core/scheduler.py
      M serving/core/trace_generator.py
      ?? experiments/pd_kv_ep/configs/ep_ep_minimal/
      ?? experiments/pd_kv_ep/configs/generate_batch_miss_minimal.py
      ?? experiments/pd_kv_ep/configs/generate_minimal_1p2d_rank_mapped_tp2.py
      ?? experiments/pd_kv_ep/configs/generate_two_decode_ep4_groups_flowsim.py
      ?? experiments/pd_kv_ep/configs/large_scale/flowsim/
      ?? experiments/pd_kv_ep/configs/large_scale/minimal_1p2d_ep16_logical_to_physical.json
      ?? experiments/pd_kv_ep/configs/large_scale/minimal_1p2d_ep16_rank_mapped_tp2.json
      ?? experiments/pd_kv_ep/configs/large_scale/ns3/minimal_1p2d_ep16_logical_ranks_single_tor.txt
      ?? experiments/pd_kv_ep/scripts/test_config_topology_rank_count.py
      ?? experiments/pd_kv_ep/scripts/test_flowsim_collective_scope.py
      ?? experiments/pd_kv_ep/scripts/test_flowsim_decode_completion_wakeup.py
      ?? experiments/pd_kv_ep/scripts/test_flowsim_decode_handoff_wakeup.py
      ?? experiments/pd_kv_ep/scripts/test_flowsim_group_queue_ownership.py
      ?? experiments/pd_kv_ep/scripts/test_flowsim_rank_mapping.py
      ?? experiments/pd_kv_ep/scripts/test_ns3_config_topology_selection.py
      ?? experiments/pd_kv_ep/scripts/test_pd_request_pairing.py
      ?? experiments/pd_kv_ep/scripts/test_trace_time_units.py
      ?? experiments/pd_kv_ep/workloads/minimal_cross_request_ep_round_aligned.jsonl
      ?? experiments/pd_kv_ep/workloads/minimal_cross_request_no_overlap_control.jsonl
      ?? experiments/pd_kv_ep/workloads/minimal_cross_request_overlap.jsonl
      ?? experiments/pd_kv_ep/workloads/minimal_ep4_decode_cohort.jsonl
      ?? experiments/pd_kv_ep/workloads/minimal_ep4_then_kv8192.jsonl
      ?? experiments/pd_kv_ep/workloads/minimal_ep4_then_tiny_request.jsonl
      ?? experiments/pd_kv_ep/workloads/minimal_kv_kv_control_i128.jsonl
      ?? experiments/pd_kv_ep/workloads/minimal_kv_kv_control_i2048.jsonl
      ?? experiments/pd_kv_ep/workloads/minimal_kv_kv_control_i32.jsonl
      ?? experiments/pd_kv_ep/workloads/minimal_kv_kv_control_i8192.jsonl
      ?? experiments/pd_kv_ep/workloads/minimal_kv_kv_distinct_sizes.jsonl
      ?? experiments/pd_kv_ep/workloads/minimal_kv_kv_i128_i2048.jsonl
      ?? experiments/pd_kv_ep/workloads/minimal_kv_kv_i128_i8192.jsonl
      ?? experiments/pd_kv_ep/workloads/minimal_time_unit_corrected_kv_control.jsonl
      ?? experiments/pd_kv_ep/workloads/minimal_time_unit_corrected_kv_ep_overlap.jsonl
      ?? experiments/pd_kv_ep/workloads/moe_i1_o2_n1.jsonl
      ?? experiments/pd_kv_ep/workloads/moe_i1_o3_n1.jsonl
      ?? experiments/pd_kv_ep/workloads/two_ep4_groups_a_only_2req.jsonl
      ?? experiments/pd_kv_ep/workloads/two_ep4_groups_a_only_4req.jsonl
      ?? experiments/pd_kv_ep/workloads/two_ep4_groups_full_4req.jsonl
      ?? experiments/pd_kv_ep/workloads/two_ep4_groups_full_8req.jsonl
      ?? research_audit/
      ?? research_motivation/
      ?? serving/core/flowsim_groups.py
- The exact historical shell command used for the two integrated serving runs was not saved. The CLI flags below were checked against the current entry point; they document a reproducible invocation shape, not a claim that shell history was captured verbatim.

## Environment and rerun commands

Python: `/home/lpm/.conda/envs/llmsim-flowsim/bin/python` (Python 3.10 environment). The system `python` is not the intended interpreter. Runtime environment:

    PYTHONPATH=/home/dell/lpm/LLMServingSim:/home/dell/lpm/LLMServingSim/astra-sim/extern/graph_frontend
    PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python
    FLOWSIM_TELEMETRY_CLASSES=KV_MOVEMENT
    FLOWSIM_MAX_FLOW_TELEMETRY_ROWS=4096
    FLOWSIM_EP_FLOW_TELEMETRY=0

Integrated run command shape for N1 (substitute N4 workload/output/run-id for the four-request result):

    python -m serving --cluster-config experiments/pd_kv_ep/configs/large_scale/minimal_1p2d_ep16_rank_mapped_tp2.json --dataset ../research_motivation/kv_handoff/workloads/post_prefill_i2048_o8_1req.jsonl --network-backend flowsim --pd-kv-transfer-mode POST_PREFILL --flowsim-topology experiments/pd_kv_ep/configs/large_scale/flowsim/minimal_1p2d_ep16_single_tor_nvlink.txt --flowsim-rank-map experiments/pd_kv_ep/configs/large_scale/minimal_1p2d_ep16_logical_to_physical.json --flowsim-policy FAIR --request-routing-policy RR --dtype bfloat16 --max-num-seqs 8 --flowsim-telemetry /tmp/kvpost-n1-repro-flows.jsonl --output /tmp/kvpost-n1-repro.csv --run-id kvpost-n1-repro

For N4, substitute the N4 workload and unique `n1-repro` output/run names with `n4-repro`. These example outputs go to `/tmp` so they do not overwrite the saved authoritative CSVs or telemetry.

The four-request run used the same flags with dataset `post_prefill_i2048_o8_4req.jsonl`, output folder `v3_post_prefill_i2048_o8_4req_fair`, and a distinct run ID. ASTRA input artifacts and telemetry are kept in their result folders. Exact historical run IDs/command line were not preserved, so the above is a reproduction template and should not be confused with captured provenance.

Network replay command, rerun successfully in this audit:

    PYTHONPATH=/home/dell/lpm/LLMServingSim:/home/dell/lpm/LLMServingSim/astra-sim/extern/graph_frontend PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python FLOWSIM_TELEMETRY_CLASSES=KV_MOVEMENT FLOWSIM_MAX_FLOW_TELEMETRY_ROWS=4096 FLOWSIM_EP_FLOW_TELEMETRY=0 /home/lpm/.conda/envs/llmsim-flowsim/bin/python research_motivation/kv_handoff/analyze_handoff_replay.py --single-flow-file research_motivation/kv_handoff/results/v2_post_prefill_i2048_o8_1req/flows.jsonl --multi-flow-file research_motivation/kv_handoff/results/v3_post_prefill_i2048_o8_4req_fair/flows.jsonl --topology experiments/pd_kv_ep/configs/large_scale/flowsim/minimal_1p2d_ep16_single_tor_nvlink.txt --expected-out /tmp/kv_handoff_expected.verify.csv --results-out /tmp/kv_handoff_network.verify.csv

The two temporary CSV outputs compared byte-for-byte with the checked-in working result CSVs. `py_compile` passed for the current serving entry, trace generator, Chakra converter, and replay script; `git diff --check` passed.

## Hashes

SHA-256 at report creation:

| Artifact | SHA-256 |
|---|---|
| `serving/core/trace_generator.py` | `65e54faf30dbc51638aa5f7a0c3b554fe8248060a74576f7dbdb70dc95923aa5` |
| `serving/__main__.py` | `74d9b87d86aab35f2652f91e596ceb52ef200e12eebf52ff3e8f57b12c6b16f6` |
| `astra-sim/extern/graph_frontend/chakra/src/converter/llm_converter.py` | `8f5b6c1d0c00d21a40ce2990fa6773d803be4874dac345cf969434d08fe421f9` |
| rank-mapped cluster config | `93abc0562ab3bb26c2955c25604e28ec3620465852dd80452726d5427931ff7b` |
| FlowSim topology | `3fa000e6ff3b26fb77f00645a0ddac82f993ca0e831e4abd5cd208baa14995ca` |
| logical-to-physical rank map | `5b7c91e6b1937e23bcc342655f9335f9a1dc3b43b2f52affa9a3c29ebdd6ba41` |
| model config | `0736f3bafb95cc658776c92ab34f5f98d8169634a3a36b84892d71448a1f19d3` |
| profile `meta.yaml` | `e755433ea63a19e9d4a4919f04da412807aa520972dc97df3dfb8908b6a70f96` |
| TP2 dense profile | `710f04261d67ec53639095cec91751c9a9dc1aa6f5b335c9decaee4802407633` |
| TP2 attention profile | `0b0fb7a5436cb4bffba5e89397cf747064b1566e0053db4584c70d766d243b10` |
| TP1 MoE profile | `aa6e29a17412a62234a6610d7a699f72e5938f09386374b635925c5db29045f6` |
| replay script | `0270be19a31d910df1d460c3ed66ad3b4090d52b9a05fe83bc2cf3951b4635e8` |
| N1 workload | `c0413559fd64117a674d16c88509970cd3e8f55d2f27b056476a3636408ad6db` |
| N4 workload | `4c48d6b8bd908c79863c82555fe78ea6e0ad61d8b23d6aa5967d62c735f6eb29` |
| theoretical CSV | `2e6a463ea58c69273c9dce7a666f0aa6de1292c0d361631dbc7f83a7444876a3` |
| network replay CSV | `ef875b836ff5f0ffba5ae70de7bb22777da79e02409bf20eed3c5cd65d8c20ad` |
| N1 request CSV | `0ee3c23568676261635cb735f1e694e0516d93cf405bf984c56328eb66649878` |
| N4 request CSV | `888859e5ecf89379adaa65106cbd71b8b5cab07fad8d9f1f4fe09cc0830776cc` |

Note: the rank-map hash was captured from the current file and should be rechecked before a later rerun if the worktree changes.

## Data classification and exclusions

- Correct integrated evidence: `results/v2_post_prefill_i2048_o8_1req/` and `results/v3_post_prefill_i2048_o8_4req_fair/`.
- Compact release/completion/path ledger: `04_P2D_FLOW_LEDGER.csv`; raw source is each run folder's `flows.jsonl`.
- Network-only counterfactual: `02_EXPECTED_NETWORK_GAIN.csv`, `03_NETWORK_ONLY_RESULTS.csv`, generated from those actual integrated flow ledgers.
- Invalid, excluded, not deleted: `results/post_prefill_i2048_o8_1req.flow_telemetry.jsonl` (124 MiB). The earlier attempt had incorrect full-cache byte accounting and excessive telemetry volume; it is not authoritative.
- `v1_post_prefill_i2048_o8_1req/` contains an incomplete early artifact and is not used.
- No integrated REQUEST_GROUPED/FIFO/SRPT/COFLOW run, active-Decode-EP-overlap run, or 8-versus-10 layerwise fan-in run was executed.
