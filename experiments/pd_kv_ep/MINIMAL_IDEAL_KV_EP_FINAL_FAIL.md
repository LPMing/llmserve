# Minimal Ideal KV–EP Gate: FINAL FAIL

## Decision

**`MINIMAL_IDEAL_KV_EP_FINAL_FAIL`**

The most favorable bounded legal FlowSim case, D16K8, verified simultaneous
model-derived P2D KV and Decode EP peer traffic on the same directed 200-Gbps
ToR ingress. Nevertheless, EP collective CCT P99 increased only 5.11% and
request-level KV residual-drain P99 only 3.66% against matched isolated
baselines. Both are below the predeclared 10% stop threshold. KV-ready time
did not change; integrated D TBT P99 changed 0.47%. Stop the
KV-transfer × Decode-EP shared-fabric contention line under this simulator and
tested physical envelope. Do not scale further or search traces for a
collision.

This is a FlowSim/serving-level negative result, not a packet-level ns-3
validation. No packet run was warranted: no qualifying barrier mechanism was
found to validate. FlowSim fluid backlog is not switch-buffer occupancy and
does not model packet serialization, ECN, PFC, or congestion control.

## Topology and semantic correctness

- Physical cluster: P0 + D0 + D1, eight GPUs/server, two independent
  200-Gbps NICs/server (400 Gbps aggregate/server). Four GPU ranks attach to
  each NIC over the local high-rate abstraction. This is not eight independent
  50-Gbps GPU links.
- Network: one ToR; six NIC-to-ToR physical links at 200 Gbps each; no spine,
  intentional oversubscription, or path pinning. The FlowSim representation
  preserves the distinct NIC links. D0 and D1 have separate full-duplex
  directed ToR resources.
- Decode: Qwen3-30B-A3B-Instruct-2507, 48 layers, 128 experts, top-k 8, EP16
  over the 16 Decode GPU ranks. Intra-server EP stays on the local endpoint
  attachment; cross-server EP can traverse the ToR.
- P2D receiver mode is ACTUAL. Each Prefill worker is paired to a real Decode
  scheduler instance. Decode admission waits for the required KV transfer
  barrier.
- P2D uses LAYERWISE and native model-derived BF16 KV bytes. For 8192 input
  tokens, this is 16,777,216 B/layer before destination TP sharding and
  805,306,368 B/request across 48 layers. No synthetic byte override was used.
- EP uses the model/GateRouter-derived A2A_P2P peer flows. EP CCT is measured
  as last required peer completion minus collective start, not individual
  P2P-flow latency.
- K is injected only after the D-only warm-up shows all intended D requests
  admitted and four Decode token boundaries completed. Injection times were
  66.034225 ms for D2/D4/D8 and 70.607649 ms for D16; there is no fixed
  hand-chosen delay. K requests use 8192 input tokens and two output tokens,
  the minimum that lets the integrated request complete and retire.

The topology permits a true common resource. For example, a P0→D0 KV shard
and a D1→D0 EP peer can both use directed `ToR→D0 NIC0` at 200 Gbps. D2K1 did
not place its K and active D traffic on that common scale-out cut, so D2K1 is
retained as a topology/placement diagnostic only. D4K1 and all later points
positively observed P2D/EP overlap on a shared directed ToR ingress.

## Metric definitions

- **EP CCT**: collective start to last required EP peer completion; compared
  over the interval from event-derived K injection to the first K Decode
  admission. K's own EP is excluded.
- **KV residual drain**: request's last required KV shard completion minus
  release of its final KV layer. It is a request-level barrier tail, not a sum
  of shard FCTs.
- **KV handoff/ready**: request arrival to all-required-KV-ready. With
  LAYERWISE generation this includes the layer-release span; it is not the
  network drain time alone.
- **Queue**: FlowSim analytical residual-fluid backlog. The queue-episode
  duration is measured per directed ToR link. It is not physical switch
  occupancy.
- **TTFT/TBT/TPOT**: read only from completed integrated serving request CSVs.
  No SLO thresholds were configured for this gate, so no SLO attainment is
  claimed. These are simulated serving latencies, not wall-clock run times.

Within a point, all K requests have identical prompt length and simultaneous
arrival; the resulting request-level residual-drain samples are equal, so
mean and P99 coincide. This does not mean KV FCT was calculated by summing
flows: the statistic is the last-required-shard request barrier. Different
K population points have separate matched KV_ONLY baselines.

## Matched results

All rows use FAIR. Isolated columns are D-only EP/TBT and K-only KV/TTFT runs
with the same request sizes, model, topology, and event-derived arrival time.
The two deltas are network/serving results from separate metrics and should
not be conflated.

| Point | KV bytes | EP bytes | EP CCT mean, isolated→FULL | EP CCT P99, isolated→FULL | EP P99 change | KV residual P99, isolated→FULL | KV residual change | K TTFT P99, isolated→FULL | D TBT P99, isolated→FULL |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| D2K1* | 0.805 GB | 0.391 GB | 17.266→17.266 us | 23.022→23.022 us | 0.00% | 177.973→177.973 us | 0.00% | 371.130→378.298 ms (+1.93%) | 5.563056→5.563056 ms (0%) |
| D4K1 | 0.805 GB | 0.743 GB | 17.266→17.295 us | 23.022→23.350 us | +1.42% | 177.973→180.595 us | +1.47% | 371.130→375.034 ms (+1.05%) | 5.851056→5.853352 ms (+0.04%) |
| D8K1 | 0.805 GB | 1.486 GB | 17.266→17.306 us | 23.022→23.514 us | +2.14% | 177.973→183.218 us | +2.95% | 371.130→375.480 ms (+1.17%) | 5.851056→5.854664 ms (+0.06%) |
| D8K2 | 1.611 GB | 1.485 GB | 17.266→17.426 us | 23.022→24.115 us | +4.75% | 345.745→355.579 us | +2.84% | 374.667→375.911 ms (+0.33%) | 5.851056→5.864392 ms (+0.23%) |
| D8K4 | 3.221 GB | 1.483 GB | 17.266→17.561 us | 23.022→24.006 us | +4.27% | 681.289→687.518 us | +0.91% | 374.955→376.332 ms (+0.37%) | 5.851056→5.875328 ms (+0.41%) |
| D16K4 | 3.221 GB | 2.794 GB | 19.232→19.468 us | 25.644→26.299 us | +2.55% | 681.289→708.734 us | +4.03% | 374.955→380.211 ms (+1.40%) | 6.214912→6.229977 ms (+0.24%) |
| **D16K8** | **6.442 GB** | **2.789 GB** | **19.232→19.585 us** | **25.644→26.954 us** | **+5.11%** | **681.289→706.196 us** | **+3.66%** | **374.955→380.967 ms (+1.60%)** | **6.214912→6.244387 ms (+0.47%)** |

*D2K1 had time overlap but no shared ToR-scaleout path observed in its
placement/captured window; it is not evidence of network contention.

The strongest point is D16K8, not a 20% result. Its EP CCT mean increases
1.83%; D-cohort TBT mean increases from 6.214912 to 6.237057 ms (+0.36%),
while TPOT P99 increases from 6.165975 to 6.180598 ms (+0.24%). Request-level
KV-ready remains 368.624 ms in both KV_ONLY and FULL. The measured serving
TTFT increase therefore must not be presented as P2D network delay: the
request ledger shows a 5.599-ms Decode-admission wait in FULL and a 6.743-ms
first-token iteration versus 6.331 ms in KV_ONLY.

## Queue and path evidence at the final point

- P2D/EP active-window overlap: 41.531010 ms.
- EP scale-out peer-flow/round pairs overlapping KV: 134,480; 100,320 include
  a last-completing peer. These are pair counts, not unique flows, bytes, or
  distinct collectives.
- Shared directed ingress paths include `ToR→D0 NIC0/1` and
  `ToR→D1 NIC0/1`, each a 200-Gbps resource in the model.
- Peak residual-fluid backlog: 16,775,791 B overall, 8,445,132 B on Decode
  ingress. P95 positive-queue episode: 3.258 us; median EP period: 6,236.527
  us; queue-persistence ratio: 0.000522. Thus queue episodes are about
  0.052% of an EP period, rather than persisting across collective rounds.
- The filtered EP scale-out-flow detail limit was reached at 473.838 ms, after
  the measurement end at 439.232 ms, so path-overlap attribution covers the
  barrier window. ToR link telemetry has 323,210 samples and its final sample
  is 1.068 us before the scheduler-defined window end; telemetry truncation
  later in the run is flagged. Queue values remain fluid estimates.

Peak utilization equals modeled capacity during some event intervals, but
instantaneous utilization is not evidence of sustained overload. The queue
duration relative to EP period, barrier deltas, and unchanged KV-ready event
are the decisive signals here.

## Interpretation and boundary

The experiment establishes that the data-plane paths can overlap on the same
directed physical-resource abstraction. It does **not** establish that this
overlap materially delays an EP collective barrier or the last-shard KV
handoff in the tested FlowSim model. Even with all eight 8192-token K requests
arriving together at the event-derived Decode steady state, 6.44 GB of model-
derived P2D KV, 16 active Decode requests, and verified 200-Gbps shared ToR
ingress, both network barrier slowdowns remain below 10%. The K requests' KV
readiness is unchanged; their TTFT delta is dominated by Decode admission and
first-token serving time. D TBT changes by less than half a percent.

The limiting factors consistent with the observed data are:

1. **Layerwise release slack**: the request KV handoff spans 368.624 ms, while
   final residual drain is only 0.706 ms in the strongest point. Earlier-layer
   transfer time is hidden behind later-layer generation.
2. **The selected legal fabric is not persistently saturated**: 200-Gbps
   ingress links see transient fluid backlog, but queue episodes are only a
   few microseconds, compared with EP periods of roughly 6.2 ms.
3. **Cross-traffic changes individual peer service little at the collective
   tail**: many peer-path overlaps are observed, yet collective P99 moves only
   5.11% at D16K8.

This is a negative result for the specified max-min FlowSim model and this
single controlled workload family. It is not evidence that all packet-level
RoCE deployments are contention-free; FlowSim does not include packet queues,
ECN/DCQCN, PFC, QP scheduling, or packetization. Under the user's stop rule,
however, do not use that limitation to justify more traces, lower bandwidth,
smaller buffers, larger synthetic bytes, or larger populations. The minimum
ideal legal FlowSim gate is FINAL FAIL, so this KV×EP direction stops here.

## Run provenance and retained artifacts

- Numeric ledger: [`results/minimal_ideal_kv_ep/MINIMAL_IDEAL_KV_EP_EXPERIMENTS.csv`](results/minimal_ideal_kv_ep/MINIMAL_IDEAL_KV_EP_EXPERIMENTS.csv)
- Per-point request CSVs and compact event summaries remain under
  `results/minimal_ideal_kv_ep/points/`.
- Topology and endpoint audit:
  [`MINIMAL_1P2D_TOPOLOGY_AUDIT.md`](MINIMAL_1P2D_TOPOLOGY_AUDIT.md)
- Iteration notes:
  [`MINIMAL_IDEAL_KV_EP_RESEARCH.md`](MINIMAL_IDEAL_KV_EP_RESEARCH.md)
- Historical generated outputs outside the current gate were cleaned; source,
  configurations, and current gate artifacts were retained.
