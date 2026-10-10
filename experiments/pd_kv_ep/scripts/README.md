# Script entry points

The runnable entry points are kept one directory above this folder so they can
be invoked directly as documented in the experiment README. The
`generate_workloads.py` helper creates native-token distributions, including
the time-varying EP-heavy/KV-heavy/EP-heavy workload. It contains no network
model or byte override.

## Bounded large-scale replay

`run_real_trace.py` is the only entry point for packet/cycle replay of the
converted production traces. It always materializes the selected rows into a
replay JSONL, so `--request-offset` cannot silently be ignored by the serving
frontend. A single run is capped at 25,000 requests. Its default artifact
directory is `experiments/pd_kv_ep/results/real_trace`; use `--output-root`
only when an explicitly separate result root is needed.

`--load-scale` rebases the selected slice to zero and multiplies only its
offered arrival rate: `0.5` is half load and `2.0` is double load. Token
counts, request order, session/prefix fields, and
model-derived KV/EP accounting are unchanged; the replay manifest records the
load factor and the derived interval factor, and each materialized row retains
`source_arrival_time_ns`. This is the load-scaling mechanism for the planned
`0.5x/1.0x/1.5x/2.0x` experiments, not a synthetic byte or delay override.

S4/S8 configurations are restricted to one-request communication gates with
`--allow-small-gate`; they are not large-scale trace results. Trace replay is
restricted to S64/S256.

Large traces default to concise output:

- `--log-interval 60` records serving summaries at a coarse time granularity;
- `--network-telemetry summary` keeps only compact per-link summary output;
- `--network-telemetry-interval-ms 1000` coarsens native link timeseries
  sampling when validation telemetry is enabled (queue accounting remains
  event-accurate); the generated queue monitor uses the same cadence, so the
  default does not enqueue the legacy 100-ns queue-sampling loop;
- `--ns3-binary` can select an explicitly audited optimized native binary;
  the selected path is stored in the run manifest;
- `--packet-payload-size` is an explicit packetization sensitivity knob for
  feasibility gates; leaving it unset preserves the 1,000-byte backend
  template value and all reported default-packet results;
- per-flow events, link time series, issue logs, and controller iteration logs
  are enabled only with `--network-telemetry validation` for a selected
  candidate window. The verbose frontend/controller IPC trace is still
  opt-in via `--controller-trace`; it is not needed for network validation.

The compact `.sim.log` retains final request/latency/throughput summaries and
errors, while intentionally dropping per-rank and per-iteration ASTRA output.
The wrapper also sets `LLMSERVINGSIM_COMPACT_LOGS=1`, which disables ASTRA's
default spdlog console/rotating-file sinks for the bounded replay; the serving
protocol markers needed by the frontend are still consumed internally. The
native ns-3 frontend emits a compact machine-readable rank report (`R rank
iteration cycle communication`) rather than constructing verbose per-rank
prose; `Controller` parses this protocol form before the `Waiting` marker.
Use `estimate_large_scale_cost.py` before increasing a window or request
count; its flow/runtime numbers are planning bounds, not measured results.

The wrapper converts an external `SIGINT`/`SIGTERM` into an explicit `ABORTED`
manifest and terminates the child simulator. An interrupted large-scale job
therefore cannot be mistaken for a still-running or completed experiment.

`summarize_real_trace_runs.py` scans bounded replay manifests and emits
`real_trace_execution_summary.csv/.json/.md`. It reports completion status,
wall time, generated batch progress, request CSV presence, and total ASTRA
artifact footprint; it also scans native `network_run_manifest.json` files and
records packet payload, telemetry cadence, event count, and partial event rows.
Old unfinished `RUNNING` manifests are labeled `STALE_RUNNING` in the
generated audit after one hour; source manifests are left untouched. Incomplete
rows are explicitly excluded from performance interpretation.

`run_model_derived_replay.py` is the native ns-3 data-plane-only path for a
selected S64/S256 candidate window. It keeps compact `replay.log`,
`comm_events.csv`, and coarse link/queue telemetry. Use
`--telemetry-interval-ms` to enlarge sampling cadence and
`build_model_derived_replay.py --ep-bin-us` to control model-derived EP event
coalescing. Pass the same `--load-scale` to the builder when creating a
scaled replay; the factor is stored in `replay_manifest.json` and is checked
by the runner when `--load-scale` is supplied. Use
`--kv-subtype REMOTE_KV_FETCH` only with Mooncake block-hash
traces; it preserves the hash identity and computes matched bytes from model
KV geometry. The default placement is the producing Prefill worker; use
`--remote-cache-placement dedicated_cache_nodes --remote-cache-topology
<generated-topology>` for the one-cache-endpoint-per-leaf counterfactual. Its
output is network CCT/overlap evidence, not closed-loop
TTFT/TPOT. The optional `--policy FAIR|EP_FIRST|KV_FIRST` selects native
RDMA QP/switch priority treatment; it does not change serving scheduling.
`plot_native_replay_results.py` converts completed FULL, KV_ONLY, and EP_ONLY
analyses into CSV, PNG, and PDF figures. `analyze_policy_results.py` and
`plot_policy_results.py` summarize the post-discovery static-priority
comparison.

Each native replay directory is single-use by default: the runner refuses to
overwrite an existing `network_run_manifest.json`, `comm_events.csv`, or
`link_summary.csv`. Use a new directory for another policy; reserve
`--allow-overwrite` for an intentional, separately audited rerun.

`analyze_serving_policy_results.py` summarizes request-level TTFT/TPOT/latency
CSV files for a matched serving slice. It is intentionally separate from the
native CCT analyzer: the analytical ASTRA backend does not implement the
shared-link QP arbitration used by native ns-3, so analytical policy runs are
serving-semantic gates rather than policy-attribution results.

The native S64 serving gate uses the same analyzer with
`--run-name-suffix _suppressed`; `plot_serving_policy_results.py` emits the
matched TTFT/TPOT/P2D-ready P99 figure as CSV, PNG, and PDF. Large-scale
serving runs default to `WARNING`, `--log-interval 60`, compact ASTRA logs,
and coarse/disabled discovery telemetry. Use `--packet-payload-size` only as
an explicitly recorded feasibility knob; it is not a workload-byte override.

`analyze_slo_results.py` computes the MFS, Splitwise, and DistServe-style
normalized metrics only when a baseline CSV is supplied. `--baseline-kind
low_load` is required for paper-valid SLO interpretation; `same_slice_gate`
is retained for diagnostics and is marked `invalid_for_paper` in JSON/Markdown.
The analyzer also warns and marks a low-load baseline with fewer than 10
completed requests as diagnostic-only.

`analyze_load_scale_sweep.py` consumes matched native FULL/KV_ONLY/EP_ONLY
directories and writes collective-level EP P99, KV completion P99, slowdown,
exact directed-link overlap, and completion coverage to CSV/JSON/Markdown.
`plot_load_scale_sweep.py` turns the same CSV into the corresponding CSV/PNG/PDF
figure and labels it as network-only evidence.
