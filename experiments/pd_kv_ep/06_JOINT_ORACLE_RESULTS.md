# Joint oracle results and evidence gap

## Required comparison

A synergy claim requires the same request set, arrivals, input/output lengths, model-derived KV/EP bytes, routing, topology, compute profile and measurement window in all four cells:

| Cell | System scheduling | Network scheduling | Serving result |
|---|---|---|---|
| Baseline | current | FAIR | Required |
| Network-only | current | network oracle/policy | Required |
| System-only | legal system alternative | FAIR | Required |
| Joint | same system alternative class | network oracle/policy | Required |

Define gain consistently on a lower-is-better metric, e.g. Gain(X)=1-Metric(X)/Metric(Baseline). Then Synergy=Gain(Joint)-max(Gain(Network-only),Gain(System-only)). Use paired requests/tokens, not differences between aggregate percentiles from unrelated populations.

## Surviving evidence mapped to cells

| Evidence | Closest cell | Workload identity matched? | Network delta | Serving delta | Can estimate synergy? |
|---|---|---|---:|---:|---|
| Natural Azure Conversation/Code, FAIR vs EP_FIRST | Baseline vs network-only | Yes within each Azure pair | EP CCT P99 ~0% | TTFT/TBT/TPOT ~0% | No system-only or joint cell |
| Controlled EP64, FAIR vs EP_FIRST | Baseline vs network-only, controlled | Yes within controlled pair | EP CCT P99 -50.54% | TBT P99 -21.72%, TPOT -17.26% | No system-only or joint cell; not natural |
| Progressive Push vs whole transfer at 200G | System/release-only sensitivity, separate workload | Matched within its own pair, not with Azure/EP64 cells | Network exposure/release changes | TTFT P99 -6.07%; TBT unchanged | No common four-cell experiment |
| S16 corrected fan-in ns-3 vs FlowSim serving | Network and integrated diagnostics, separate backend runs | Not same completion-coupled run | Packet EP CCT P99 +29.1%; flow FCT P99 +34.9% | Separate FlowSim TBT P99 +5.01% | No |
| EP32 packet priority vs FlowSim policy summary | Split backends and run semantics | No exact packet feedback | EP_FIRST EP CCT -0.52%; KV handoff same | Separate FlowSim KV_FIRST TBT P99 +95.9% | No |
| 512-request fan-in FlowSim | Network-only | N/A | EP P99 +201%; KV P99 +99% for fan-in16 | Not measured | No |

## Result

The four-cell factorial is NOT RUN and not estimable from retained artifacts. The single-layer results are not interchangeable: one is a controlled EP64 serving run, another is a natural Azure pair, another is progressive transfer, and packet runs do not feed completions back into serving. Do not add or multiply gains across them.

No measured joint gain, no synergy value, no exposure-guided oracle headroom, and no claim that both single-layer controls fail while joint succeeds.

## Smallest legitimate validation

Use one naturally selected exposure window, without changing arrivals or bytes. Freeze and hash the exact request list, generated communication ledger, routing, topology, model/profile and random seeds. Run:

1. Baseline system + FAIR network.
2. Network-only oracle/policy; release/admission events fixed.
3. System-only legal batch/admission/release variant; FAIR network.
4. Joint variant with identical legal controls enabled.

Instrument for each communication: release, eligible/start, finish, next serving barrier, baseline slack, predicted deficit, actual request/token barrier, TTFT/TBT/TPOT. Include compute and batch epoch timing. Counterfactual bytes and model work must match. Report mean and tail, paired confidence intervals across trace windows/seeds, and any admission/throughput/SLO cost.

Only proceed to this run if exposure scanning finds a natural window with a plausible >=20% barrier opportunity; otherwise further simulator implementation is not justified.

