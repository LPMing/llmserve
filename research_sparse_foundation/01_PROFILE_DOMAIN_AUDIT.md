# 01 — MoE compute profile domain audit

## Profile inspected

`profiler/perf/RTXPRO6000/Qwen/Qwen3-30B-A3B-Instruct-2507/bf16/tp1/moe.csv`

- 50 measured rows, produced on NVIDIA RTX PRO 6000 Blackwell Server Edition;
- token grid: `1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048`;
- `activated_experts` grid: `8, 16, 32, 64, 128`;
- sidecar audit counts are reproducible with `audit_inputs.py` and recorded in `audit_snapshot.json`.

The profiler metadata says the engine used vLLM 0.19.0, a one-layer model
override for layerwise measurement, TP=1 execution with per-rank shapes emulated,
and RTXPRO6000 hardware. This is measured data, but only over the CSV grid.

## EP-degree coverage for Qwen's 128 experts

The following is the *maximum expert count hosted per EP rank*, not necessarily
the count activated by a particular batch. A batch may activate fewer experts.

| EP | Experts/rank | Profile status for that endpoint |
|---:|---:|---|
| 4 | 32 | Present on the activated-expert grid |
| 8 | 16 | Present |
| 16 | 8 | Present at the minimum measured value |
| 32 | 4 | Below measured minimum; clamp-sensitive |
| 64 | 2 | Below measured minimum; clamp-sensitive |

Having a grid point at 32/16/8 does not validate every query: `route_ep()` may
return a smaller per-rank `activated_experts` value at low token counts.

## Historical sidecar query-domain audit

The 2,078 retained `*.a2a_routes.json` sidecars contain 64,670 rank-query
templates weighted to 3,104,160 layer-equivalent queries using
`trace_repetitions`. These sidecars are retained artifacts, not a census of all
historical runs.

| Query status | Weighted queries | Interpretation |
|---|---:|---|
| Both axes on a measured grid point | 1,152 | 24 templates × 48 layers |
| Token axis in-domain but interpolated; activated-expert axis below minimum | 1,536 | Token interpolation does not repair the AE clamp |
| Token axis above maximum; AE axis on-grid | 288 | 6 templates × 48 layers; token extrapolation |
| Activated-expert below-minimum | 3,102,720 | **99.9536%** of weighted queries; `_lookup_bounds()` clamps to AE=8 |
| Activated-expert on-grid | 1,440 | Remaining 0.0464% |

The run-level breakdown is in `audit_snapshot.json`. All retained sidecars are
`BALANCED`; their `EXACT_P2P_ROUTED_ALLTOALL` label describes a converter
realization of an analytic/synthetic matrix, not actual model-router evidence.
For example, the inspected record has `source_token_origin=
dp_wave_actual_scheduled_tokens`, `routing_policy=BALANCED`, `top_k=8`,
`ep_size=32`, and `trace_repetitions=48`. That provenance identifies token
counts and a deterministic approximation, not selected expert IDs from Qwen.

## Lookup implications

`serving/core/trace_generator.py::_lookup_moe()` brackets/interpolates within
the `activated_experts` table, but `_lookup_bounds()` clamps a query below the
minimum to the first available AE row. Queries above the maximum extrapolate
from the last two rows. Thus the historical EP32/EP64 MoE compute times are not
calibrated at their natural 4/2-expert-per-rank operating points. A plausible
interpolated number is not a measurement.

The token axis is mostly in-domain in the retained route sidecars; this does not
remove the dominant activated-expert domain error. Six token-axis templates
exceed 2,048 and are extrapolated.

## Calibration result

`PROFILE_MEASUREMENT_UNAVAILABLE`: `nvidia-smi -L` reports that it cannot
communicate with the NVIDIA driver. No profiler was run. Activated-expert
measurements at 1, 2, and 4 and additional coverage of the actual token range
remain prerequisites for quantitative EP32/EP64 Serving timing.

**Gate:** profile provenance passes for the measured grid; quantitative use at
EP32/EP64 actual activated-expert counts **does not pass**. Do not use those
clamped latencies as exact evidence for P0 or P1 Serving gains.
