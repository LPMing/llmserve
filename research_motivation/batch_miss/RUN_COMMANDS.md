# Reproduction commands

Run from repository root with the conda environment used for the measurements. `CHAKRA_SHIM` below is an environment-provided temporary compatibility shim; Chakra protobuf support is a dependency of this checkout and the shim itself is not tracked by this experiment. Output paths under `/tmp` are scratch; the compact exports under `results/` are retained.

```bash
export PYTHONPATH=.:/tmp/llmsim-chakra-shim.TzDOXs
export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python
PY=/home/lpm/.conda/envs/llmsim-flowsim/bin/python
```

## Generate workloads and 400G sensitivity config

```bash
$PY research_motivation/batch_miss/generate_workload.py \
  --output research_motivation/batch_miss/E1_target_2048_r0_24_workload.jsonl \
  --target-arrival-ns 30000000 --interferer-count 0 --target-input 2048 \
  --r0-count 24 --r0-output 16 --candidate-output 8

$PY research_motivation/batch_miss/generate_workload.py \
  --output research_motivation/batch_miss/E3_target_plus_3x2048_r0_24_workload.jsonl \
  --target-arrival-ns 30000000 --interferer-count 3 --interferer-offset-ns 0 \
  --target-input 2048 --interferer-input 2048 --r0-count 24 \
  --r0-output 16 --candidate-output 8

$PY research_motivation/batch_miss/generate_workload.py \
  --output research_motivation/batch_miss/E4_R2_staggered_100ms.jsonl \
  --target-arrival-ns 30000000 --interferer-count 3 --interferer-offset-ns 100000000 \
  --target-input 2048 --interferer-input 2048 --r0-count 24 \
  --r0-output 16 --candidate-output 8

$PY research_motivation/batch_miss/generate_sensitivity_config.py
```

## Run template

For each run, set unique `OUT` and `RUN`; choose `CONFIG`, `DATASET`, `NREQ`, and `POLICY` from the table below. The flow telemetry and graph/scheduler event streams are bounded/opt-in. In the 200G E3/E4 and 400G E3 runs, compute-node completion logging is limited to graph IDs 8 and 9; the logger has no effect on service events.

```bash
OUT=/tmp/$RUN
mkdir -p "$OUT"
env PYTHONPATH="$PYTHONPATH" \
  PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python \
  SERVING_BATCH_MISS_EVENT_LOG="$OUT/scheduler.jsonl" \
  FLOWSIM_EXEC_DEBUG_PATH="$OUT/graph.jsonl" \
  FLOWSIM_EXEC_DEBUG_EVENTS=submit,graph_completed,compute_node_completed \
  FLOWSIM_EXEC_DEBUG_COMPUTE_GRAPH_IDS=8,9 \
  FLOWSIM_FLOW_TELEMETRY=1 FLOWSIM_MAX_TELEMETRY_ROWS=5000 \
  FLOWSIM_MAX_FLOW_TELEMETRY_ROWS=20000 \
  "$PY" -m serving --cluster-config "$CONFIG" --dataset "$DATASET" \
  --num-reqs "$NREQ" --network-backend flowsim --flowsim-policy "$POLICY" \
  --request-routing-policy RR --max-num-seqs 8 --max-num-batched-tokens 2048 \
  --no-enable-prefix-caching --no-enable-chunked-prefill --log-level WARNING \
  --run-id "$RUN" --output "$OUT/requests.csv" \
  --flowsim-telemetry "$OUT/flowsim.jsonl" > "$OUT/stdout.log" 2>&1
```

| Run | `RUN` | `CONFIG` | `DATASET` | `NREQ` | `POLICY` |
|---|---|---|---:|---:|---|
| E0 | `batch_miss_E0_single` | `research_motivation/batch_miss/minimal_1p2d_ep4_config.json` | `research_motivation/batch_miss/E0_single_2048.jsonl` | 1 | FAIR |
| E1 | `batch_miss_E1` | same 200G config | `E1_target_2048_r0_24_workload.jsonl` | 25 | KV_ISOLATED |
| E2 | `batch_miss_E2` | same 200G config | same as E1 | 25 | FAIR |
| E3a | `batch_miss_E3a_final` | same 200G config | `E3_target_plus_3x2048_r0_24_workload.jsonl` | 28 | KV_ISOLATED |
| E3b | `batch_miss_E3b_final` | same 200G config | same as E3a | 28 | FAIR |
| E3 400G | `batch_miss_E3_400g` | `minimal_1p2d_ep4_400g_config.json` | same as E3a | 28 | FAIR |
| E4 | `batch_miss_E4_staggered` | same 200G config | `E4_R2_staggered_100ms.jsonl` | 28 | FAIR |

To regenerate the exported summary and compact ledgers after all run directories exist:

```bash
$PY research_motivation/batch_miss/export_batch_miss_results.py \
  --e0-requests /tmp/bm_single_requests.csv --e0-flows /tmp/bm_single_telemetry.jsonl \
  --e1-dir /tmp/bm_e1 --e2-dir /tmp/bm_e2 \
  --e3a-dir /tmp/bm_E3a_final --e3b-dir /tmp/bm_E3b_final \
  --e3-high-bandwidth-dir /tmp/bm_E3_400g \
  --e4-staggered-dir /tmp/bm_E4_staggered \
  --output-dir research_motivation/batch_miss/results
```

The `KV_ISOLATED` policy is a virtual independent-capacity counterfactual, not a deployable network policy. It isolates EP from KV by giving each class a separate virtual copy of each link; it does not eliminate KV-vs-KV contention.
