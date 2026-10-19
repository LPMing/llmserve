#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-/home/lpm/.conda/envs/llmsim-flowsim/bin/python}"
OUT_ROOT="${1:?usage: bash run_integrated_controls.sh OUT_ROOT [MAIN|NEIGHBORS|ALL]}"
MODE="${2:-MAIN}"
MAIN_DATASET="$SCRIPT_DIR/seed_plus_two_targets_crosscut.jsonl"
mkdir -p "$OUT_ROOT"
OUT_ROOT="$(cd "$OUT_ROOT" && pwd)"

run_case() {
    local label="$1"
    local policy="$2"
    local request_first_id="$3"
    local dataset="$4"
    local network_classes="$5"
    local run_dir="$OUT_ROOT/$label"
    local -a extra_args=()

    mkdir -p "$run_dir"
    if [[ -n "$request_first_id" ]]; then
        extra_args+=(--flowsim-request-first-id "$request_first_id")
    fi

    (
        cd "$ROOT"
        export PYTHONPATH="$ROOT/astra-sim/extern/graph_frontend${PYTHONPATH:+:$PYTHONPATH}"
        export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python
        export FLOWSIM_NETWORK_CLASSES="$network_classes"
        export FLOWSIM_TELEMETRY_LINK_IDS='12->13,13->12'
        export FLOWSIM_TELEMETRY_START_NS=70000000
        export FLOWSIM_TELEMETRY_END_NS=81000000
        export FLOWSIM_MAX_TELEMETRY_ROWS=4096
        export SERVING_BATCH_MISS_EVENT_LOG="$run_dir/events.jsonl"
        "$PYTHON_BIN" -m serving \
            --cluster-config research_motivation/decode_opportunity/decode_opportunity_2p2d_tp2.json \
            --dataset "$dataset" \
            --network-backend flowsim \
            --flowsim-topology research_motivation/decode_opportunity/two_prefill_two_decode_shared_cut_200g.txt \
            --flowsim-rank-map research_motivation/decode_opportunity/rank_map_2p2d_tp2_cross_cut.json \
            --flowsim-policy "$policy" "${extra_args[@]}" \
            --request-routing-policy RR \
            --pd-kv-transfer-mode POST_PREFILL \
            --dtype bfloat16 \
            --max-num-seqs 1 \
            --max-num-batched-tokens 2048 \
            --log-interval 1000 \
            --flowsim-telemetry "$run_dir/flows.jsonl" \
            --output "$run_dir/requests.csv" \
            --run-id "${label}-$(basename "$OUT_ROOT")"
    )
}

run_main() {
    run_case C0_KV_ONLY_NETWORK FAIR '' "$MAIN_DATASET" KV_MOVEMENT
    run_case S0_FAIR FAIR '' "$MAIN_DATASET" KV_MOVEMENT,EP
    run_case S1_KV_FIRST_REQ3 KV_REQUEST_FIRST 3 "$MAIN_DATASET" KV_MOVEMENT,EP
    run_case S2_EP_FIRST EP_FIRST '' "$MAIN_DATASET" KV_MOVEMENT,EP
    run_case S3_FIFO_COFLOW_TIE_REQ2 EP_THEN_KV_REQUEST_FIRST 2 "$MAIN_DATASET" KV_MOVEMENT,EP
    run_case S4_DECODE_OPPORTUNITY_REQ3 EP_THEN_KV_REQUEST_FIRST 3 "$MAIN_DATASET" KV_MOVEMENT,EP
}

run_neighbors() {
    run_case B11_FAIR FAIR '' "$SCRIPT_DIR/seed_plus_two_targets_crosscut_d0_o11.jsonl" KV_MOVEMENT,EP
    run_case B11_OPPORTUNITY EP_THEN_KV_REQUEST_FIRST 3 "$SCRIPT_DIR/seed_plus_two_targets_crosscut_d0_o11.jsonl" KV_MOVEMENT,EP
    run_case B13_FAIR FAIR '' "$SCRIPT_DIR/seed_plus_two_targets_crosscut_d0_o13.jsonl" KV_MOVEMENT,EP
    run_case B13_OPPORTUNITY EP_THEN_KV_REQUEST_FIRST 3 "$SCRIPT_DIR/seed_plus_two_targets_crosscut_d0_o13.jsonl" KV_MOVEMENT,EP
}

case "$MODE" in
    MAIN) run_main ;;
    NEIGHBORS) run_neighbors ;;
    ALL) run_main; run_neighbors ;;
    *) echo "unknown mode '$MODE' (expected MAIN, NEIGHBORS, or ALL)" >&2; exit 2 ;;
esac
