# KV/EP Policy Characterization

Primary discovery runs use Qwen3 model-derived bytes, FlowSim, and
`--pd-kv-transfer-mode LAYERWISE`; the integrated validation points below use
the same model-derived request and routing semantics. FlowSim queue values are
residual fluid backlog, not packet-buffer occupancy. Network-only TTFT/TBT/SLO
values are intentionally unavailable.


## Round round1

This round was selected from the prior layerwise result: one large P2D request produced strong EP slowdown but no meaningful EP_FIRST KV cost, so this round increases P2D population, burst width, or temporal overlap without changing the model or injecting synthetic bytes.

### ep3_kv1_large_baseline

Why: Existing layerwise large-KV point; establishes the reference policy ordering.

| run | EP CCT P99 (ms) | EP slowdown | KV FCT P99 (ms) | KV slowdown | EP queue P99 (ms) | KV queue P99 (ms) | max fluid queue (MB) | mixed links |

|---|---:|---:|---:|---:|---:|---:|---:|---:|

| ep_only | 0.096 | 0.000% | n/a | n/a | 0.000 | n/a | 0.000 | 0 |

| kv_only | n/a | n/a | 143.440 | 0.000% | n/a | 0.000 | 0.000 | 0 |

| full_fair | 0.127 | 32.812% | 143.440 | 0.000% | 0.000 | 0.000 | 8.107 | 4 |

| full_ep_first | 0.096 | 0.000% | 143.440 | 0.000% | 0.000 | 0.000 | 8.389 | 4 |

| full_kv_first | 0.420 | 338.237% | 143.440 | 0.000% | 0.000 | 0.000 | 8.107 | 4 |


Observed crossover candidate: **not yet**. 
EP_FIRST KV penalty = 0.000%; KV_FIRST EP penalty = 338.237%.

The corresponding serving-level TTFT/TPOT/TBT/SLO fields are **not available from this network-only round**.

### ep2_kv2_medium_burst

Why: Increase concurrent P2D population from one to two while retaining a Decode cohort.

| run | EP CCT P99 (ms) | EP slowdown | KV FCT P99 (ms) | KV slowdown | EP queue P99 (ms) | KV queue P99 (ms) | max fluid queue (MB) | mixed links |

|---|---:|---:|---:|---:|---:|---:|---:|---:|

| ep_only | 0.064 | 0.000% | n/a | n/a | 0.000 | n/a | 0.000 | 0 |

| kv_only | n/a | n/a | 13.000 | 0.000% | n/a | 0.000 | 0.000 | 0 |

| full_fair | 0.064 | 0.000% | 13.000 | 0.000% | 0.000 | 0.000 | 0.000 | 0 |

| full_ep_first | 0.064 | 0.000% | 13.000 | 0.000% | 0.000 | 0.000 | 0.000 | 0 |

| full_kv_first | 0.064 | 0.000% | 13.000 | 0.000% | 0.000 | 0.000 | 0.000 | 0 |


Observed crossover candidate: **not yet**. 
EP_FIRST KV penalty = 0.000%; KV_FIRST EP penalty = 0.000%.

The corresponding serving-level TTFT/TPOT/TBT/SLO fields are **not available from this network-only round**.

### ep2_kv2_large_burst

Why: Test whether two moderate/large layerwise handoffs create an EP_FIRST KV-side penalty.

| run | EP CCT P99 (ms) | EP slowdown | KV FCT P99 (ms) | KV slowdown | EP queue P99 (ms) | KV queue P99 (ms) | max fluid queue (MB) | mixed links |

|---|---:|---:|---:|---:|---:|---:|---:|---:|

| ep_only | 0.064 | 0.000% | n/a | n/a | 0.000 | n/a | 0.000 | 0 |

| kv_only | n/a | n/a | 45.956 | 0.000% | n/a | 0.000 | 1.238 | 0 |

| full_fair | 0.064 | 0.000% | 45.956 | 0.000% | 0.000 | 0.000 | 1.238 | 0 |

| full_ep_first | 0.064 | 0.000% | 45.956 | 0.000% | 0.000 | 0.000 | 1.238 | 0 |

| full_kv_first | 0.064 | 0.000% | 45.956 | 0.000% | 0.000 | 0.000 | 1.238 | 0 |


Observed crossover candidate: **not yet**. 
EP_FIRST KV penalty = 0.000%; KV_FIRST EP penalty = 0.000%.

The corresponding serving-level TTFT/TPOT/TBT/SLO fields are **not available from this network-only round**.

### ep1_kv3_medium_sustained

Why: Test KV-concurrency amplification with three staggered P2D requests and a lighter EP cohort.

| run | EP CCT P99 (ms) | EP slowdown | KV FCT P99 (ms) | KV slowdown | EP queue P99 (ms) | KV queue P99 (ms) | max fluid queue (MB) | mixed links |

|---|---:|---:|---:|---:|---:|---:|---:|---:|

| ep_only | 0.033 | 0.000% | n/a | n/a | 0.000 | n/a | 0.000 | 0 |

| kv_only | n/a | n/a | 23.220 | 0.000% | n/a | 0.000 | 0.000 | 0 |

| full_fair | 0.036 | 8.241% | 23.220 | 0.000% | 0.000 | 0.000 | 1.028 | 4 |

| full_ep_first | 0.033 | 0.000% | 23.220 | 0.000% | 0.000 | 0.000 | 1.049 | 4 |

| full_kv_first | 0.075 | 127.265% | 23.220 | 0.000% | 0.000 | 0.000 | 0.786 | 4 |


Observed crossover candidate: **not yet**. 
EP_FIRST KV penalty = 0.000%; KV_FIRST EP penalty = 127.265%.

The corresponding serving-level TTFT/TPOT/TBT/SLO fields are **not available from this network-only round**.

### ep3_kv1_small_early

Why: Move a small handoff into the Decode-rich interval to test whether EP_FIRST is still KV-neutral.

| run | EP CCT P99 (ms) | EP slowdown | KV FCT P99 (ms) | KV slowdown | EP queue P99 (ms) | KV queue P99 (ms) | max fluid queue (MB) | mixed links |

|---|---:|---:|---:|---:|---:|---:|---:|---:|

| ep_only | 0.096 | 0.000% | n/a | n/a | 0.000 | n/a | 0.000 | 0 |

| kv_only | n/a | n/a | 5.560 | 0.000% | n/a | 0.000 | 0.000 | 0 |

| full_fair | 0.096 | 0.000% | 5.560 | 0.000% | 0.000 | 0.000 | 2.182 | 4 |

| full_ep_first | 0.096 | 0.000% | 5.560 | 0.000% | 0.000 | 0.000 | 2.182 | 4 |

| full_kv_first | 0.096 | 0.000% | 5.560 | 0.000% | 0.000 | 0.000 | 2.182 | 4 |


Observed crossover candidate: **not yet**. 
EP_FIRST KV penalty = 0.000%; KV_FIRST EP penalty = 0.000%.

The corresponding serving-level TTFT/TPOT/TBT/SLO fields are **not available from this network-only round**.


Next autonomous step: Increase concurrent/staggered P2D population or move to a sustained KV backlog; EP_FIRST has not paid a measurable KV cost yet.

## Round 4: EP64 integrated telemetry and no-backpressure audit

This round replays the same matched high-pressure serving workload under the
three data-plane policies. It uses the existing model-derived Qwen3-30B-A3B
KV/EP bytes, 8P8D, EP64, 200 Gbps, `LAYERWISE`, actual Decode destinations,
32 active Decode requests, and 64 concurrent 2048-token P2D requests. The
short output (`output_toks=1`) is intentional for this population gate: it
keeps the run finite while preserving the first Decode EP round. It provides
valid TTFT and one-token TBT, but TPOT and steady-state multi-token TBT are
not meaningful in this particular workload and are recorded as zero/missing
by the serving frontend rather than fabricated.

Run IDs:

- `ep64_telemetry_high_fair_collective_v1`
- `ep64_telemetry_high_epfirst_v1`
- `ep64_telemetry_high_kvfirst_v1`

All three runs completed with 96 requests and exact single-request KV
attribution for all 9,216 P2D layer/shard flows. The table compares policy
effects within the same workload; it is not a KV_ONLY-normalized slowdown
table.

| policy | EP CCT P99 (ms) | KV handoff FCT P99 (ms) | TTFT P99 (ms) | TBT P99 (ms) | max generated-minus-completed KV (GB) |
|---|---:|---:|---:|---:|---:|
| FAIR | 1.747824 | 285.070825 | 298.845624 | 46.927517 | 6.308 |
| EP_FIRST | 0.380377 (-78.24%) | 286.400189 (+0.47%) | 299.982055 (+0.38%) | 13.679489 (-70.85%) | 6.442 |
| KV_FIRST | 128.899535 (+7,274.86%) | 280.945042 (-1.45%) | 308.863184 (+3.35%) | 265.812184 (+466.43%) | 6.241 |

The corresponding FlowSim aggregate KV generation/drain rates were:

| policy | generation (Gbps) | drain (Gbps) | time-weighted total outstanding KV (GB) |
|---|---:|---:|---:|
| FAIR | 448.118 | 348.957 | 3.964 |
| EP_FIRST | 446.803 | 347.441 | 4.012 |
| KV_FIRST | 451.998 | 353.748 | 3.891 |

These are aggregate rates over all model-derived P2D shards, not a claim that
one physical link sustained those rates. FlowSim queue values remain
analytical residual-fluid backlog, not packet-buffer occupancy, ECN, PFC, or
drop measurements.

### Interpretation

The no-backpressure model does not mean that KV has no network cost. In this
workload, generated KV exceeds the drain capacity over the active interval,
and generated-minus-completed KV reaches roughly 6.2--6.4 GB. The absolute
KV handoff and TTFT therefore include a common-mode P2D backlog.

However, `EP_FIRST` changes that common-mode KV result by less than 1% versus
`FAIR`. This indicates that the small policy delta is not explained only by
the absence of outstanding-KV accounting. The current layerwise frontend
continues producing/releasing later KV shards without waiting for earlier
network completion, while the EP bursts occupy short recurrent intervals;
the final KV admission delay is dominated by the broad P2D release/drain
timeline rather than by the strict-priority decision at each EP burst.

The reverse direction is clear: `KV_FIRST` protects the KV drain but causes
large Decode EP barrier delays, and the integrated one-token TBT P99 follows
that EP CCT increase. This is a valid cross-request contention result, not a
same-request P2D-to-Decode overlap: each request still waits for its complete
KV handoff before Decode admission.

### Telemetry and critical-path accounting

`kv_event_telemetry.jsonl` now distinguishes `KV_GENERATED`, actual network
`KV_REQUESTED`/released, `KV_STARTED`, and `KV_COMPLETED`. The analyzer writes
`kv_timeseries.csv` with generated, released, staged, network-outstanding, and
completed bytes; `kv_request_metrics.csv` records the last-completing KV
flow/layer, queue/service time, path overlap, handoff span, post-prefill
drain, `p2d_kv_ready_time`, and TTFT. ITL is parsed from the real token-level
JSON sequence; no missing TPOT/TBT value is filled in.

The high-pressure telemetry satisfies the condition for a sensitivity study:
outstanding KV persists and aggregate generation rate is above aggregate
drain rate. An optional `FINITE_BUFFER` FlowSim mode has therefore been added,
defaulting to `OFF`; it gates later P2D network release per prefill-rank/request
at a user-specified model-derived byte capacity. It does not alter the default
serving semantics or the existing results. The next sensitivity run should
use capacities around the observed per-request shard stream (for example
16/32/64 MiB), and must be reported separately as finite-buffer sensitivity,
not as the default system model.

Current conclusion: the EP64 high-pressure workload demonstrates strong
EP-critical policy asymmetry and TBT impact, but it does **not** yet establish
an `EP_FIRST`-versus-`FAIR` KV-side crossover. The finite-buffer sensitivity
must determine whether realistic sender staging can turn the common-mode KV
backlog into a policy-specific TTFT penalty.

### Finite-buffer smoke sensitivity: 8D + 8P2D

The first completed sensitivity uses the existing low-pressure EP64 workload,
32 MiB per prefill-rank/request buffer, `LAYERWISE`, and the same model-derived
KV bytes. It is a sender-side release gate: later P2D shards remain staged
until earlier shards drain. It does not silently change the default run.

| run | max total outstanding (GB) | max network outstanding (GB) | max staged (GB) | KV FCT P99 (ms) | TTFT P99 (ms) |
|---|---:|---:|---:|---:|---:|
| no-BP FAIR | 1.024 | 1.024 | 0 | 65.571 | 70.301 |
| finite-buffer FAIR | 0.908 | 0.537 | 0.487 | 65.571 | 71.176 |
| finite-buffer EP_FIRST | 0.908 | 0.537 | 0.487 | 65.571 | 71.176 |

The finite buffer is functioning: it lowers network-resident outstanding KV
from 1.024 GB to 0.537 GB and creates 0.487 GB of explicitly staged KV. The
low-pressure point nevertheless shows no KV FCT change and only a small
absolute TTFT change (about 0.875 ms, 1.24% versus the available no-BP FAIR
reference). FAIR and EP_FIRST are identical here because this workload does
not create a policy-sensitive EP/TTFT boundary at the chosen buffer size.

The first 32 MiB high-pressure attempt produced only intermediate telemetry
and no complete request CSV, so it is excluded from all claims. Its partial
files are not used as serving results. High-pressure finite-buffer sensitivity
requires a separately completed matched run before drawing a KV-side policy
conclusion.

### Completed high-pressure finite-buffer matched control

The completed 32 MiB high-pressure runs are
`ep64_telemetry_high_fair_bp32m_v1` and
`ep64_telemetry_high_epfirst_bp32m_v2`. They use the same 32D+64P2D request
set as the no-BP runs.

| policy | EP CCT P99 (ms) | KV FCT P99 (ms) | TTFT P99 (ms) | TBT P99 (ms) | max total outstanding (GB) | max staged (GB) |
|---|---:|---:|---:|---:|---:|---:|
| FAIR, no BP | 1.747824 | 285.070825 | 298.845624 | 46.927517 | 6.308 | 0 |
| EP_FIRST, no BP | 0.380377 | 286.400189 | 299.982055 | 13.679489 | 6.442 | 0 |
| FAIR, 32 MiB BP | 1.055880 | 285.028701 | 298.741470 | 28.760167 | 4.765 | 2.617 |
| EP_FIRST, 32 MiB BP | 0.380377 | 286.382053 | 299.922104 | 13.651404 | 4.865 | 2.718 |

Within the finite-buffer matched pair, EP_FIRST changes KV FCT P99 by only
0.47% and TTFT P99 by 0.40% relative to FAIR, while reducing EP CCT P99 by
63.97% and TBT P99 by 52.54%. The finite buffer therefore changes the common
KV resident/staged state substantially, but does not create the hypothesized
EP_FIRST-specific KV/TTFT crossover in this realistic EP64 workload.

This is an important negative result. Under the current FlowSim sender-side
sensitivity, the path

`EP_FIRST -> lower KV drain rate -> buffer exhaustion -> TTFT tail`

is not observed as a policy-specific effect at 32 MiB. The high-pressure
network remains EP-critical, while the KV handoff is dominated by the shared
P2D release/drain schedule. A full GPU producer stall or NIC credit model
would be a different extension and is not silently claimed here.

The current evidence consequently supports the following bounded statement:
static EP protection is strongly useful for Decode EP/TBT, but neither the
default no-BP model nor the tested finite sender-release buffer has yet shown
that EP_FIRST materially harms KV FCT/TTFT. The dynamic-policy crossover
hypothesis remains unproven rather than established.

## Round 5: EP round criticality and offline selective protection

This round uses the same EP64/8P8D/200 Gbps high-pressure workload and
`A2A_P2P` routing. It adds an optional per-flow EP ledger containing source,
destination, bytes, path, requested/start/finish, queueing, completion rank,
layer, dispatch/combine type, and the round's last-completion marker.

The FAIR baseline contains 880 EP rounds and 67,248 unique EP flows after
deduplicating fixed-point replay records. The result is not a uniformly
single-critical-flow collective: flows often tie at the final timestamp.

| protected set from FAIR oracle | mean protected-flow count / round | mean protected EP bytes |
|---|---:|---:|
| all EP (`EP_FIRST` upper bound) | all | 100% |
| last-completing tied flows (`CRITICAL_ONLY`) | 28.2 | 40.83% |
| slowest 5% per round | 4.3 | 6.47% |
| slowest 1% per round | 1.1 | 1.72% |

The last-completing set is therefore not “a few packets”: in this routing and
batching configuration it averages about 40.8% of EP bytes. The slowest-flow
sets provide a genuine selective upper-bound test rather than a synthetic
traffic modification.

### Offline oracle results

The `CRITICAL_ONLY` run gives strict-priority treatment only to the FAIR
baseline's last-completing flow IDs; all other EP flows share FAIR capacity
with KV. `TOP5` uses the FAIR baseline's slowest 5% flow IDs.

| policy | EP CCT P99 (ms) | TBT P99 (ms) | KV FCT P99 (ms) | TTFT P99 (ms) |
|---|---:|---:|---:|---:|
| FAIR | 1.747824 | 46.927517 | 285.070825 | 298.845624 |
| EP_FIRST | 0.380377 (-78.24%) | 13.679489 (-70.85%) | 286.400189 (+0.47%) | 299.982055 (+0.38%) |
| CRITICAL_ONLY | 1.613334 (-7.69%) | 37.644748 (-19.78%) | 285.115526 (+0.02%) | 299.268748 (+0.14%) |
| TOP5 | 1.744686 (-0.18%) | 46.997430 (+0.15%) | 285.419066 (+0.12%) | 299.307018 (+0.15%) |

The selective oracle does not reproduce `EP_FIRST`'s EP/TBT protection. The
last-completing set is also unstable as a critical set: although 99.99% of
the baseline oracle flow IDs are present in the matched replay, only a much
smaller subset is last-completing after the policy changes. This is exactly
the difficulty an online critical-flow predictor would face.

The top-5% oracle protects only about 6.5% of EP bytes and produces essentially
FAIR-level EP CCT/TBT. It provides no measurable KV/TTFT headroom beyond the
already-small `EP_FIRST` KV cost. The available headroom is therefore not
useful in this workload: reducing protected EP traffic also removes most of
the EP benefit.

### TBT critical-path limitation and attribution

The telemetry now establishes the network-side chain:

`EP flow completion rank -> collective last completion -> scheduler batch -> TBT`

`layer_id`, `event_type`, `batch_id`, request cohort, and round ID are retained
for every EP flow. In the current 32D+64P2D gate, Decode requests use
`output_toks=1`; consequently TBT is a real one-token TBT and TPOT is zero by
definition. It is not valid to claim a steady-state multi-token TBT fraction
from this short-output gate. A multi-token replay is required if a paper figure
needs per-token `critical_EP_time / TBT` over later Decode iterations.

For the present gate, `CRITICAL_ONLY` reduces EP CCT P99 by only 7.69% and
TBT P99 by 19.78%, while changing KV FCT/TTFT by less than 0.2%. `EP_FIRST`
remains the only tested policy that strongly protects EP/TBT, but it protects
all EP traffic and does not expose additional KV/TTFT headroom here.

### Multi-token attribution validation

To avoid treating the one-token gate as a complete serving result, the same
32 Decode + 64 P2D workload was replayed with Decode `output_toks=4` under
FAIR.  This run completed with 1,232 EP rounds and 110,160 deduplicated EP
flows.  The integrated request ledger reports TTFT P99 = 302.777 ms, TPOT
P99 = 32.363 ms, and token TBT P99 = 51.544 ms.  These numbers are from the
serving ledger, not inferred from network CCT.

The analyzer maps an EP round to a token only when the round's request cohort
contains exactly one request.  It therefore retains 25 exact token rows and
marks the remaining 135 rows as `no_exact_round_mapping`; those 135 rows are
not used for the exact critical-path summary.  For the 25 exact rows, the
union of EP-round intervals accounts for a median 34.89% of TBT, P95 78.72%,
and P99 85.50%.  The union, rather than a sum of overlapping CCTs, is used so
overlapping EP rounds cannot inflate the fraction above the token interval.

This confirms that EP communication can be a substantial part of TBT for
some single-request token steps, while also exposing an instrumentation limit:
the current batched collective metadata does not provide an exact per-request
decomposition for every round.  The result is sufficient for the offline
criticality gate, but not a claim that every token's TBT is fully attributable
to one request's EP flows.

Current direction decision: the static EP_FIRST policy is close to the useful
Pareto point for this EP64 workload. `CRITICAL_ONLY`/top-k selective protection
does not currently justify a new scheduler design. Further KV–EP scheduling
work should stop unless a multi-token, trace-backed workload shows materially
different critical-flow stability.

## EP64 balanced 8P8D follow-up

The next search step used a balanced `8P:8D` physical cluster rather than the
earlier 1P2D/tiny topology.  Each server has eight physical GPU/rank
endpoints, each instance is TP2, and the 32 Decode instances form one EP64
group.  The Qwen3-30B-A3B model configuration supplies 128 experts, top-k 8,
and 48 transformer layers, so EP64 is a valid partition with two experts per
EP rank.  The topology is a four-leaf/two-spine 200-Gbps Clos with 1:1
aggregate leaf-spine capacity and P:D server and GPU ratios of 1:1.

The replay ledger uses model-derived layerwise P2D and GateRouter-derived EP
routing.  Active Decode requests emit EP only; later requests emit P2D only.
This is an explicit matched phase-control workload, not a byte override.  The
FlowSim queue remains a residual-fluid quantity, not a packet-buffer queue.

| active Decode | concurrent P2D | EP_ONLY CCT P99 (ms) | FULL FAIR EP CCT P99 (ms) | FAIR EP slowdown | KV_ONLY FCT P99 (ms) | FULL FAIR KV slowdown | EP_FIRST KV slowdown | artifact |
|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 8 | 8 | 0.272 | 3.635 | +1237.9% | 64.445 | +7.03% | +7.03% | `ep64_network_characterization` |
| 16 | 16 | 0.523 | 13.037 | +2391.3% | 128.869 | +15.06% | +15.23% | `ep64_network_characterization_decode16_p2d16` |
| 16 | 24 | 0.523 | 13.037 | +2391.3% | 128.869 | +15.06% | +15.23% | `ep64_network_characterization_decode16_p2d24` |
| 16 | 64 | 0.523 | 27.796 | +5213.0% | 257.718 | +11.72% | +11.72% | `ep64_network_characterization_decode16_p2d64` |
| 32 | 64 | 1.027 | 32.689 | +3084.1% | 257.718 | +23.44% | **+23.44%** | `ep64_network_characterization_decode32_p2d64` |

The EP64 result establishes a network-side KV-critical regime: with 32 active
Decode requests and 64 concurrent 2048-token P2D requests, EP_FIRST still
protects EP CCT, but request-level KV handoff FCT is 23.44% above the matched
KV_ONLY baseline.  Thus EP_FIRST is not free once Decode concurrency and P2D
population jointly raise the shared-fabric pressure.

The 16-Decode/24-P2D point being identical to the 16-Decode/16-P2D point is a
useful negative result.  It shows that request count alone is not sufficient:
the 1:1 Clos still has enough parallel service opportunities in that regime.
The stronger 32-Decode/64-P2D point changes Decode offered load and crosses the
KV-side threshold without changing the per-request KV size.

These values are controlled replay observations.  The P99 values are nearly
identical to the corresponding medians in each point because the generated
requests and collective bins are intentionally homogeneous; they are not yet
production-trace tail evidence.  Also, these runs do not provide integrated
TTFT/TPOT/TBT.  The first 8P8D integrated FlowSim attempt was terminated before
an output CSV was produced, so no serving metric is inferred from it.

The 64-P2D `KV_FIRST` replay did not complete within the bounded runtime and
has no artifact; it is recorded as an execution-limit observation, not a
latency result.  Lower-pressure matched runs already show that KV_FIRST can
protect KV while causing very large EP CCT degradation.  The next valid step
is to make the 32-Decode/64-P2D point integrated-serving runnable, then verify
whether the network-side +23.44% KV handoff increase propagates to TTFT, while
retaining this controlled replay as mechanism evidence.


## Integrated serving rounds and real-trace validation

The network-only rounds above already satisfy the EP-side network motivation
target: `FAIR` reaches +42.403%, +55.866%, +97.671%, and +286.340% EP CCT P99
slowdown at several model-derived layerwise operating points, while
`EP_FIRST` removes that EP-side slowdown. They do **not** establish a KV-side
policy penalty. The following runs were added to test whether the same effect
survives the integrated scheduler and whether a policy crossover appears.

### Real BurstGPT S64: negative/control evidence

The 64-request FlowSim replay used the converted BurstGPT trace without
changing request sizes or order. The sparse `window_006925` slice had only
about 1.58 ms of global KV/EP temporal overlap over a 0.84 s activity span;
FAIR, EP_FIRST, and KV_FIRST were indistinguishable. The higher-pressure
`window_074181` slice, including a 4x inter-arrival compression used only as a
load-scaling experiment, produced EP_FIRST KV P99 penalties of only about
1.12% (1x) and 1.72% (4x, 1 ms EP aggregation). This is valid negative
evidence: the previous prose-only `+24.7%` BurstGPT summary has no raw replay
artifact in the current checkout and is not counted as verified evidence.

### Integrated 1P2D/EP2/100-Gbps correctness and weak-overlap gate

`integrated_ep2_mixed4_*` is a matched two-request run with the same request
set and topology under all three policies. It completed in roughly 1.6--2.0 s
wall time with about 120 MB RSS and produced complete request CSVs containing
TTFT, TPOT, and token TBT arrays. Its shared-link overlap is real but only
about 38 microseconds in the FAIR run, so the policy differences are below
measurement significance. This is retained as the fast integrated correctness
gate, not as motivation evidence.

### Integrated EP-side motivation: 2 active Decode + 2 P2D

The strongest completed integrated point is
`integrated_ep4_100g_2ep2kv_*`: two 64-token active Decode requests and two
simultaneous 2048-token P2D requests, Qwen3 EP4, A2A_P2P, LAYERWISE, and a
100-Gbps shared topology. All four policy runs completed with valid per-request
TTFT/TBT data in about 23--25 s wall time and about 125 MB RSS.

For the active Decode cohort, token-TBT P99 was:

| policy | active TBT P99 | active TPOT | new-P2D TTFT P99-style value |
|---|---:|---:|---:|
| FAIR | 5.683 ms | 5.251 ms | 246.550 ms |
| EP_FIRST | 5.670 ms | 5.246 ms | 246.345 ms |
| KV_FIRST | 5.767 ms | 5.405 ms | 246.856 ms |

The two active requests therefore see a small KV_FIRST penalty at this point;
it is not the primary 20% point. It confirms that the integrated serving path
maps EP arbitration into token-level TBT rather than only reporting network
flow completion.

### Integrated EP-side strong point: 3 active Decode + 1 large P2D

With three 128-token active Decode requests and one 8192-token P2D request,
the same EP4/100-Gbps/LAYERWISE setup produced the following matched result:

| policy | active Decode TBT P99 | active TPOT | large-P2D TTFT |
|---|---:|---:|---:|
| FAIR | 5.541 ms | 5.491 ms | 925.320 ms |
| EP_FIRST | 5.526 ms | 5.482 ms | 925.320 ms |
| KV_FIRST | 6.003 ms | 5.661 ms | 925.320 ms |

Relative to FAIR, KV_FIRST increases active Decode TBT P99 by **8.3%** at
100 Gbps. The corresponding 200-Gbps EP4 run is stronger: FAIR 5.845 ms,
EP_FIRST 5.777 ms, and KV_FIRST 6.675 ms, i.e. **+14.2%** TBT P99 for
KV_FIRST. The 200-Gbps point is useful as a near-threshold sensitivity result;
the 100-Gbps point is the conservative primary-link result.

The network-side effect is substantially larger than the end-to-end TBT
average because the Decode compute path absorbs part of an individual
collective delay. Grouping A2A_P2P flows by graph, subtype, and communication
tag gives EP collective CCT P99 of 11.860 us under FAIR, 9.365 us under
EP_FIRST, and 148.982 us under KV_FIRST in the 3EP+1KV/100-Gbps run. Thus
KV_FIRST causes **+1156.3% EP CCT P99** even though the corresponding active
Decode TBT P99 increase is 8.3%. This is the required distinction between a
network-side motivation metric and a serving-level consequence.

### P2D granularity sensitivity

The same 3-Decode+1-large-request set was rerun with POST_PREFILL only as a
granularity sensitivity. At 100 Gbps, FAIR versus EP_FIRST changed the large
request TTFT from 991.278 ms to 991.320 ms and P2D-ready time from 1086.070 ms
to 1086.112 ms, both about +0.004%. This does not support a KV-side 20%
penalty and is not used as the main workload conclusion.

### Explicitly incomplete stress point

`controlled_2ep2kv_8192.jsonl` (two 512-token Decode requests plus two
8192-token requests) was started as a controlled request-parameter stress
point. Its integrated LAYERWISE run exceeded the 240 s wall-time budget while
building roughly one thousand Decode graph rounds and produced no CSV. It is
therefore **not** a result and no latency is inferred from it. This also gives
an actionable cost boundary: integrated serving validation should use short
Decode cohorts after network-only discovery, while long traces/long output
remain FlowSim replay candidates unless graph generation is separately
optimized.

### Current policy conclusion

Goal A is met at the network layer: a model-derived, matched integrated regime
shows a greater than 20% EP CCT P99 penalty under KV_FIRST, and EP_FIRST
restores the Decode-side tail. The serving path maps this into a clear but
smaller TBT increase because compute and communication overlap. Goal B is
**not met**: under the tested realistic BurstGPT slice and
model-derived 1P2D LAYERWISE/POST_PREFILL points, EP_FIRST has not caused a
20% KV FCT or TTFT penalty. Therefore the current evidence does not yet justify
the claim that no fixed policy is robust. It supports the narrower statement
that KV can strongly hurt Decode EP/TBT, while the reverse penalty is
workload- and timing-sensitive and remains unproven here.

The next autonomous search should select real-trace windows with multiple
simultaneous P2D admissions and a Decode population whose EP duty cycle is
already high, use network-only discovery first, and reserve integrated runs
for a small number of short-output representative windows. No additional
synthetic byte or artificial delay should be introduced.

## EP64 integrated serving: high-pressure output=4

The next validation point kept the same 8P8D/EP64/200-Gbps topology, RR
routing, 32 active Decode requests, 64 P2D requests, 128-token Decode
prompts, 2048-token P2D prompts, and the 20-ms P2D arrival burst.  Only the
Decode output length was reduced from 16 to 4 so the integrated run could
finish without retaining hundreds of thousands of verbose flow records.  KV
and EP bytes remain model-derived; the workload generator reports
`synthetic_byte_override: false`.

The three policy runs below are valid integrated serving results.  Values are
milliseconds.  Decode TBT/TPOT are computed from the per-request CSV fields;
P2D FCT is `p2d_kv_ready_time_ns - arrival`, not the absolute ready timestamp.

| policy | Decode TTFT P99 | Decode TPOT P99 | Decode TBT P99 | P2D KV FCT P99 | P2D TTFT P99 |
|---|---:|---:|---:|---:|---:|
| FAIR | 53.713 | 15.408 | 26.041 | 283.909 | 292.119 |
| EP_FIRST | 50.472 | 4.947 | 7.421 | 283.909 | 292.119 |
| KV_FIRST | 308.127 | 5.511 | 265.076 | 280.910 | 297.238 |

Relative to FAIR, EP_FIRST reduces Decode TBT P99 by 71.5% and Decode TTFT
P99 by 6.0%, while changing P2D FCT by less than 0.001%.  KV_FIRST raises
Decode TBT P99 by 917.9% and Decode TTFT P99 by 473.7%; its P2D FCT is 1.06%
lower than FAIR.  This is a strong and reproducible EP-side integrated
motivation point, but it is not evidence that EP_FIRST itself penalizes KV.
There is no normalized SLO threshold in this round, so no SLO attainment is
reported or inferred.

Artifacts:

- `results/integrated/ep64_high32d64p2d_decode4_fair_rr_v1.csv`
- `results/integrated/ep64_high_32d64p2d_decode4_ep_first_rr_v1.csv`
- `results/integrated/ep64_high_32d64p2d_decode4_kv_first_rr_v1.csv`
- `workloads/autonomous/ep64_integrated_high_32d64p2d_decode4.jsonl`

### Interpreting the earlier +23.44% network-only KV result

The earlier EP64 network-only ledger has, for each 2048-token P2D request,
96 layer-shard flows and 201,326,592 model-derived KV bytes.  Its request
metrics are:

| control | KV FCT P99 |
|---|---:|
| KV_ONLY | 257.718 ms |
| FULL + FAIR | 318.116 ms |
| FULL + EP_FIRST | 318.116 ms |

Thus `(318.116019 / 257.718040 - 1) = 23.44%` was a **historical
FULL-vs-KV_ONLY contention cost** under the old S16 parser, which treated
each sixteen-link leaf--spine bundle as a single 200-Gbps resource.  After
the topology correction, the same recovered flow records replay at
46.192 ms for both FULL+FAIR and KV_ONLY, so the +23.44% value is no longer
valid evidence for the corrected S16 model.  It was not an
`EP_FIRST-vs-FAIR` cost even in the old ledger: the two full policies differed
by approximately one nanosecond.

The integrated layerwise serving run measures a different, more restrictive
quantity: the request is admitted only after the actual P2D DAG and its
completion barrier finish, and layerwise communication is released by the
serving graph rather than as one open-loop network batch.  Its high-pressure
output=4 FAIR P2D FCT is 283.909 ms, and EP_FIRST is 283.909 ms.  Therefore
the 23.44% network-only number must not be copied into the integrated TTFT
table.  It remains useful as a network mechanism/counterfactual result, while
the integrated CSV is the evidence for serving-level TTFT/TBT.

### Current conclusion after this round

The integrated EP64 data now closes the EP-side chain:

`cross-request P2D KV -> shared EP queueing -> Decode TBT/TTFT increase`.

It still does not close the reverse policy chain:

`EP_FIRST -> KV backlog -> KV FCT/TTFT increase`.

At this topology and workload, the shared-fabric load causes KV to be
slower than its isolated network-only baseline, but changing FAIR to
EP_FIRST does not add a measurable KV cost.  The evidence therefore supports
“EP protection is valuable and KV_FIRST is unsafe for Decode SLOs” but does
not yet support “no fixed policy is robust.”  The next useful experiment is
not more P2D requests: it is a matched high-EP workload with a longer
P2D-critical serving window or a timing window where the residual KV service
rate is policy-sensitive, followed by a network-only/integrated comparison.

## EP64 small-KV / sustained-EP sensitivity

To test whether the reverse policy effect appears when the KV transfer is
short enough for EP bursts to occupy a larger fraction of its service window,
the same 32 Decode + 64 P2D workload was rerun with 128-token P2D prompts.
The topology, EP64 routing, P2D arrival time, request routing, and
model-derived layerwise bytes were unchanged.  Decode output lengths of 4, 8,
and 16 were used only to vary EP duty cycle.

The most informative matched FAIR/EP_FIRST results are:

| Decode output | policy | Decode TTFT P99 | Decode TBT P99 | P2D TTFT P99 | P2D TBT P99 | KV FCT P99 |
|---:|---|---:|---:|---:|---:|---:|
| 4 | FAIR | 56.198 | 13.147 | 75.942 | 8.018 | 67.924 |
| 4 | EP_FIRST | 50.472 | 7.421 | 75.942 | 8.018 | 67.924 |
| 8 | FAIR | 56.198 | 13.147 | 82.416 | 14.492 | 67.924 |
| 8 | EP_FIRST | 50.472 | 7.421 | 83.016 | 15.092 | 67.924 |
| 16 | FAIR | 56.198 | 13.147 | 82.416 | 14.492 | 67.924 |
| 16 | EP_FIRST | 50.472 | 8.919 | 83.917 | 15.993 | 67.924 |

The policy deltas relative to FAIR are:

- output=4: P2D TTFT/FCT `0% / 0%`, Decode TBT `-43.55%`;
- output=8: P2D TTFT `+0.73%`, P2D TBT `+4.14%`, Decode TBT `-43.55%`;
- output=16: P2D TTFT `+1.82%`, P2D TBT `+10.36%`, KV FCT `0%`, Decode TBT
  `-32.15%`.

This is a real policy-sensitive serving effect in the P2D token timing, but it
does not constitute a KV-handoff crossover: the request-level KV FCT is
identical under FAIR and EP_FIRST at all three output lengths.  It also does
not meet the 20% KV-side target.  The result is important negative evidence:
longer EP duty cycle alone is insufficient to produce a large KV FCT penalty
under this placement and FlowSim rate model.

Artifacts:

- `results/integrated/ep64_high_32d64p2d_smallkv_decode4_fair_rr_v1.csv`
- `results/integrated/ep64_high_32d64p2d_smallkv_decode4_ep_first_rr_v1.csv`
- `results/integrated/ep64_high_32d64p2d_smallkv_decode4_kv_first_rr_v1.csv`
- `results/integrated/ep64_high_32d64p2d_smallkv_decode8_fair_rr_v1.csv`
- `results/integrated/ep64_high_32d64p2d_smallkv_decode8_ep_first_rr_v1.csv`
- `results/integrated/ep64_high_32d64p2d_smallkv_decode16_fair_rr_v1.csv`
- `results/integrated/ep64_high_32d64p2d_smallkv_decode16_ep_first_rr_v1.csv`

The next decision point is therefore not to claim a crossover.  Before
changing topology, the remaining causal check is whether the small-KV runs'
EP bursts actually share the same directed bottleneck links at the instant of
P2D service.  If link-level overlap is present but EP_FIRST still leaves KV
FCT unchanged, the evidence favors a static EP-priority policy under the
tested operating region.  If overlap is absent, the workload should be
retimed using a trace-derived burst window rather than by adding artificial
delay.

### Shared-link telemetry check

The small-KV FAIR output=4 run was repeated with bounded validation telemetry.
The integrated worker now writes completed flows to
`flow_telemetry.jsonl` and residual-fluid link samples separately to
`link_telemetry.jsonl`; the latter change is instrumentation only and does
not alter scheduling or flow completion.

The retained flow sample contains 3,232 P2D flows and 8,768 EP flows. On the
shared aggregation links `132->130` and `132->131`, the union of sampled KV
intervals overlaps the union of sampled EP intervals for 4.637 ms. The
bounded link telemetry reaches 100% analytical utilization and a maximum
residual fluid backlog of 5.141 MB on the shared `128->132`, `129->132`,
`132->130`, and `132->131` links. These values establish that the small-KV
negative result is not caused by complete path separation.

The queue values are explicitly FlowSim residual-fluid backlog. They are not
packet switch-buffer occupancy, ECN, PFC, or packet-drop measurements.
Artifact: `astra-sim/inputs/runs/ep64_integrated_high32d64p2d_smallkv_decode4_fair_rr_telemetry_v2/flowsim/`.


## Round round2

This round was selected from the prior layerwise result: one large P2D request produced strong EP slowdown but no meaningful EP_FIRST KV cost, so this round increases P2D population, burst width, or temporal overlap without changing the model or injecting synthetic bytes.

### ep2_kv2_medium_fanin_aligned

Why: Place two new medium-KV requests in one Decode pool and align layer-0 injection with a recurrent EP window.

| run | EP CCT P99 (ms) | EP slowdown | KV FCT P99 (ms) | KV slowdown | EP queue P99 (ms) | KV queue P99 (ms) | max fluid queue (MB) | mixed links |

|---|---:|---:|---:|---:|---:|---:|---:|---:|

| ep_only | 0.064 | 0.000% | n/a | n/a | 0.000 | n/a | 0.000 | 0 |

| kv_only | n/a | n/a | 13.000 | 0.000% | n/a | 0.000 | 0.000 | 0 |

| full_fair | 0.092 | 42.403% | 13.000 | 0.000% | 0.000 | 0.000 | 1.256 | 4 |

| full_ep_first | 0.064 | 0.000% | 13.000 | 0.000% | 0.000 | 0.000 | 1.049 | 4 |

| full_kv_first | 0.092 | 42.403% | 13.000 | 0.000% | 0.000 | 0.000 | 1.573 | 4 |


Observed crossover candidate: **not yet**. 
EP_FIRST KV penalty = 0.000%; KV_FIRST EP penalty = 42.403%.

The corresponding serving-level TTFT/TPOT/TBT/SLO fields are **not available from this network-only round**.

### ep2_kv2_large_fanin_aligned

Why: Test sustained large-KV fan-in on a shared Decode pool after the first round found no path overlap for default pairing.

| run | EP CCT P99 (ms) | EP slowdown | KV FCT P99 (ms) | KV slowdown | EP queue P99 (ms) | KV queue P99 (ms) | max fluid queue (MB) | mixed links |

|---|---:|---:|---:|---:|---:|---:|---:|---:|

| ep_only | 0.064 | 0.000% | n/a | n/a | 0.000 | n/a | 0.000 | 0 |

| kv_only | n/a | n/a | 46.006 | 0.000% | n/a | 0.000 | 0.000 | 0 |

| full_fair | 0.100 | 55.866% | 46.006 | 0.000% | 0.000 | 0.000 | 3.967 | 4 |

| full_ep_first | 0.064 | 0.000% | 46.006 | 0.000% | 0.000 | 0.000 | 4.194 | 4 |

| full_kv_first | 0.232 | 260.456% | 46.006 | 0.000% | 0.000 | 0.000 | 1.572 | 4 |


Observed crossover candidate: **not yet**. 
EP_FIRST KV penalty = 0.000%; KV_FIRST EP penalty = 260.456%.

The corresponding serving-level TTFT/TPOT/TBT/SLO fields are **not available from this network-only round**.

### ep1_kv3_medium_fanin_aligned

Why: Test three concurrent medium-KV handoffs into one Decode pool against a smaller but persistent EP cohort.

| run | EP CCT P99 (ms) | EP slowdown | KV FCT P99 (ms) | KV slowdown | EP queue P99 (ms) | KV queue P99 (ms) | max fluid queue (MB) | mixed links |

|---|---:|---:|---:|---:|---:|---:|---:|---:|

| ep_only | 0.033 | 0.000% | n/a | n/a | 0.000 | n/a | 0.000 | 0 |

| kv_only | n/a | n/a | 23.304 | 0.000% | n/a | 0.000 | 0.000 | 0 |

| full_fair | 0.091 | 175.793% | 23.323 | 0.083% | 0.000 | 0.000 | 3.142 | 2 |

| full_ep_first | 0.033 | 0.000% | 23.335 | 0.135% | 0.000 | 0.000 | 3.142 | 2 |

| full_kv_first | 0.091 | 175.796% | 23.304 | 0.000% | 0.000 | 0.000 | 3.142 | 2 |


Observed crossover candidate: **not yet**. 
EP_FIRST KV penalty = 0.135%; KV_FIRST EP penalty = 175.796%.

The corresponding serving-level TTFT/TPOT/TBT/SLO fields are **not available from this network-only round**.

### ep3_kv1_small_fanin_aligned

Why: Use the small-KV request at an exact EP overlap point to test the low-pressure side of the policy boundary.

| run | EP CCT P99 (ms) | EP slowdown | KV FCT P99 (ms) | KV slowdown | EP queue P99 (ms) | KV queue P99 (ms) | max fluid queue (MB) | mixed links |

|---|---:|---:|---:|---:|---:|---:|---:|---:|

| ep_only | 0.096 | 0.000% | n/a | n/a | 0.000 | n/a | 0.000 | 0 |

| kv_only | n/a | n/a | 5.560 | 0.000% | n/a | 0.000 | 0.000 | 0 |

| full_fair | 0.101 | 5.354% | 5.560 | 0.000% | 0.000 | 0.000 | 1.974 | 4 |

| full_ep_first | 0.096 | 0.000% | 5.560 | 0.000% | 0.000 | 0.000 | 1.744 | 4 |

| full_kv_first | 0.101 | 5.354% | 5.560 | 0.000% | 0.000 | 0.000 | 2.359 | 4 |


Observed crossover candidate: **not yet**. 
EP_FIRST KV penalty = 0.000%; KV_FIRST EP penalty = 5.354%.

The corresponding serving-level TTFT/TPOT/TBT/SLO fields are **not available from this network-only round**.


Next autonomous step: Increase concurrent/staggered P2D population or move to a sustained KV backlog; EP_FIRST has not paid a measurable KV cost yet.


## Round round3

This round was selected from the prior layerwise result: one large P2D request produced strong EP slowdown but no meaningful EP_FIRST KV cost, so this round increases P2D population, burst width, or temporal overlap without changing the model or injecting synthetic bytes.

### ep2_kv2_large_decodeheavy

Why: Increase Decode-side EP duty cycle by colocating two active Decode requests in the opposite pool from two large P2D fan-in requests.

| run | EP CCT P99 (ms) | EP slowdown | KV FCT P99 (ms) | KV slowdown | EP queue P99 (ms) | KV queue P99 (ms) | max fluid queue (MB) | mixed links |

|---|---:|---:|---:|---:|---:|---:|---:|---:|

| ep_only | 0.064 | 0.000% | n/a | n/a | 0.000 | n/a | 0.000 | 0 |

| kv_only | n/a | n/a | 143.776 | 0.000% | n/a | 0.000 | 0.000 | 0 |

| full_fair | 0.127 | 97.671% | 143.839 | 0.044% | 0.000 | 0.000 | 16.771 | 2 |

| full_ep_first | 0.064 | 0.000% | 143.839 | 0.044% | 0.000 | 0.000 | 16.777 | 2 |

| full_kv_first | 0.736 | 1041.821% | 143.776 | 0.000% | 0.000 | 0.000 | 16.771 | 2 |


Observed crossover candidate: **not yet**. 
EP_FIRST KV penalty = 0.044%; KV_FIRST EP penalty = 1041.821%.

The corresponding serving-level TTFT/TPOT/TBT/SLO fields are **not available from this network-only round**.

### ep1_kv3_large_decodeheavy

Why: Test whether three large layerwise P2D handoffs create an EP_FIRST KV completion cost against a sustained shared-link EP stream.

| run | EP CCT P99 (ms) | EP slowdown | KV FCT P99 (ms) | KV slowdown | EP queue P99 (ms) | KV queue P99 (ms) | max fluid queue (MB) | mixed links |

|---|---:|---:|---:|---:|---:|---:|---:|---:|

| ep_only | 0.033 | 0.000% | n/a | n/a | 0.000 | n/a | 0.000 | 0 |

| kv_only | n/a | n/a | 144.111 | 0.000% | n/a | 0.000 | 0.000 | 0 |

| full_fair | 0.127 | 286.340% | 144.143 | 0.022% | 0.000 | 0.000 | 25.160 | 2 |

| full_ep_first | 0.033 | 0.000% | 144.143 | 0.022% | 0.000 | 0.000 | 25.166 | 2 |

| full_kv_first | 1.040 | 3054.290% | 144.111 | 0.000% | 0.000 | 0.000 | 25.160 | 2 |


Observed crossover candidate: **not yet**. 
EP_FIRST KV penalty = 0.022%; KV_FIRST EP penalty = 3054.290%.

The corresponding serving-level TTFT/TPOT/TBT/SLO fields are **not available from this network-only round**.


Next autonomous step: Increase concurrent/staggered P2D population or move to a sustained KV backlog; EP_FIRST has not paid a measurable KV cost yet.
