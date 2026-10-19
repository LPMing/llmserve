# PP2 coflow screening hypothesis, frozen before run

## Scenario and sources

- **A:** `configs/model/Qwen/Qwen3-30B-A3B-Instruct-2507.json` gives 48 layers,
  four KV heads, head dimension 128 and BF16. The RTX PRO 6000 vLLM 0.19.0
  profile has measured TP2 rows for 2048-token Prefill and TP1 MoE at 128
  activated experts. `derive.py` reads exact CSV rows, without interpolation.
- **A/C:** Five physical four-GPU servers with two 200-Gbps NIC rails each are
  represented by the retained 4P1D topology. The physical rank map places PP2
  stage0 and stage1 on different GPUs of the **same** server, one TP rank of
  each stage under each NIC. Four independent Prefill instances send to one
  PP2/TP2 Decode instance. The NIC placement is a plausible deployment
  assumption, not a measurement of RTX PRO 6000 server wiring.
- **C:** Four simultaneous requests, one per Prefill, each 2048 input and
  three output tokens. This is a deterministic mechanism gate, not a natural
  arrival-trace frequency claim. EP1 avoids unsupported remote expert traffic.
- **A:** Current FlowSim uses directed max-min fluid service; OTHER/TP
  collectives are zero-duration by default. All matched cases retain the same
  simplification. We use scheduler token2/completion, not client TTFT.

## Theory and prediction

For one request, total KV is `2 * 48 * 4 * 128 * 2 * 2048 = 201,326,592 B`.
Each layer emits `2,097,152 B` per TP rank. Four concurrent sources emit one
layer wave of `8,388,608 B` into each Decode NIC rail. At 200 Gbps the
serialization floor is `0.335544 ms/wave`; all 48 layers imply `16.106127 ms`
of receiver-rail work, spread across layer releases. Exact measured profile
rows sum to `1.339101 ms` per full MoE block at 2048 tokens under the stated
128-expert assumption. Thus a same-layer four-source wave uses 25.1% of the
average block interval; with one request per Prefill and no stage overlap from
subsequent microbatches, receiver backlog should drain between waves. The
threshold is about 16 simultaneous Prefills, beyond this topology's four
source servers. `predictions.csv` gives m=1,2,4,8,16 values.

This is a *profile-bound trend model*, not a precise Serving latency model.
If every wave drains between releases, the last P2D layer can expose at most
roughly one 0.336-ms wave plus path delay after compute. A 64-ms block-compute
floor makes that <1% of completion. PP2 pipeline and sampler timing may alter
the exact fraction; the test must check actual release/finish timestamps.

## Falsifiable experiment

- **Hypothesis:** At four Prefill sources on the retained 200-Gbps topology,
  the PP2 P2D coflow does not create a large exposed receiver-cut stall.
- **Prediction:** Every request emits exactly 201,326,592 KV bytes; each
  stage emits half. Its final KV flow completes no more than a few ms after
  the last Prefill compute node, and the total tail is far below 15% of
  modeled request completion. Flow release spacing should exceed the
  ~0.336-ms four-source layer-wave service except at PP stage boundaries.
- **Null:** A sustained receiver backlog reaches later layer releases and
  delays P2D-ready/Decode admission by a large fraction of Serving time.
- **Configuration:** `experiments/pp_coflow/scripts/run_gate.py` generates a
  4P1D PP2/TP2/EP1 config and four-request workload from the retained topology.
- **Baseline:** Current LAYERWISE plus FlowSim FAIR with fixed resources;
  no weak flow-ordering or intentionally slow cut.
- **Metrics:** Per-request P2D-ready, token2 and completion; per-flow bytes,
  src/dst rank, path, release and finish; Prefill batch completion.
- **Pass for a paper motivation:** A >15% exposed Serving critical-path
  component remains and cannot be removed by a simple topology-aware Decode
  endpoint or layerwise transfer. This one-Decode gate can only establish
  existence of the bottleneck, not algorithmic headroom.
- **Fail:** The last flow finishes before or just after Prefill graph
  completion and there is no substantial P2D-ready→token2 propagation.
- **Confounders:** TP/PP `OTHER` cost is uncalibrated, FlowSim lacks packet
  overhead, default first-token field is graph-completion proxy, PP2 may
  overlap stages or emit unexpected duplicate KV. Audit all of these rather
  than treating a completion-time delta alone as evidence.
