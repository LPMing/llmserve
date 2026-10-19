# 06 — Final GO/NO-GO: KV/EP flow-level priority

## Decision

```text
FINAL_KV_EP_FLOW_SCHEDULING_NO_GO
```

This closes the **tested KV/EP flow-priority paper line** for the audited
Qwen3-30B-A3B configuration and available serving/network model. It is not a
universal claim that KV and EP never contend in deployed clusters.

## Gate summary

| Gate | Status | Finding |
|---|---|---|
| A — simulator path correctness | `PARTIALLY_VALIDATED` | The selected FlowSim/P2D receiver, rank, request-pairing, group-scope and admission regression path passed 31 tests. Historical outputs are not all bound to immutable commits; FlowSim is fluid, and new sparse replay is not integrated. |
| B — natural contention exposure | `FAIL_FOR_FROZEN_GATE` | Azure prefixes show route coactivity, but not a matched causal collective/handoff penalty. KV completion remains hidden by Prefill slack. |
| C — serving-visible headroom | `FAIL` | Strong controlled EP64 effect exists, but natural policy changes are near zero and several other serving-visible effects are <1% or phase-sensitive. No robust global ≥5% headroom is supported. |
| D — novelty / competitive baselines | `NOT_ESTABLISHED` | Nuska/MFS and prior flow/coflow/collective scheduling overlap. Complete Nuska, EDF/LLF, SRPT and coflow matched comparisons were not run; therefore no claim that they are inferior is permitted. |
| E — deployable scheduler/oracle | `NOT_RUN` | The earlier opportunity gates do not justify implementing a new scheduler or running a large algorithm matrix. |

## Why stop

- Large shard/flow metrics do not consistently reach the serving barrier.
- Natural Azure coactivity is not causal exposure; the last required KV shard
  completes before Prefill completion with measurable slack.
- EP_FIRST has a large controlled Decode benefit, but it did not show the
  hypothesized natural KV/TTFT cost in the tested operating points.
- Small corrected shared-ToR FAIR contention remained modest at the request and
  token level.
- A new sparse-A2A screen is not valid motivation: its apparent geometry gap
  exists without P2D and its “uniform” route construction changes destination
  concentration and expert assignment.

## Evidence limitations

`NOT_RUN` is not zero. The final policy matrix against complete Nuska,
EDF/LLF/SRPT and a global offline oracle was not executed. The conclusion is a
research-direction stop based on insufficient natural/serving headroom and
novelty not established—not a benchmark result showing those baselines lose.

See [`01_EVIDENCE_LEDGER.md`](01_EVIDENCE_LEDGER.md),
[`02_CRITICAL_PATH_HEADROOM.md`](02_CRITICAL_PATH_HEADROOM.md), and
[`03_NATURAL_WORKLOAD_EXPOSURE.md`](03_NATURAL_WORKLOAD_EXPOSURE.md).

