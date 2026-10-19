# Network-staged dual-memory handoff and backpressure

## Scenario and provenance

Qwen3-32B BF16 TP2/PP1 uses measured RTX PRO 6000 per-rank profile (A).
The 2048-token prompt and 600-token output are a bounded scenario (C),
not an observed trace pair; two 200-Gb/s rails are the retained topology
(C). Full prompt KV is 536,870,912 B, or 268,435,456 B/rank. Each rail
needs at least 10.737 ms to serialize a request, excluding transport setup.

## Compute, memory, cut and critical path

The measured 2048-token Prefill block is 2,875.951 µs; one/four-source
layer service is 167.772/671.089 µs on one rail. Thus the previous 1P1D
and 4P1D FlowSim runs both reached 184.907-ms P2D-ready, with the last
four-source KV flow 2.453 ms *before* that barrier. For cold isolated
requests, a zero-network Oracle cannot advance the measured barrier;
`Gain_upper=0` for network staging in this envelope. The even looser fully
serial transfer share is only `10.737/(184.907+10.737)=5.49%` before
Decode service, so changing stage time cannot create a 10% gain here.

With 128 active 2048+600-token sequences, the optimistic per-rank D pool
has 118,880 tokens free, enough for 58 more full 2048-token handoffs.
Measured-profile compute-only limits are 5.416 Prefill requests/s and
3.986 Decode requests/s at this long output. One P can outpace one D;
1P2D is a necessary resource-ratio comparator. The critical path after
memory fills would include P-source KV retention, receiver acceptance,
network transfer and D admission; the present simulator frees P memory
before D allocation and raises when full. No saturated latency prediction
is therefore accepted.

## Baselines, Oracle, status and falsifier

Strong baselines are capacity-aware FIFO/SRPT/EDF with exact memory,
topology-aware D choice, tuned P:D ratio, [DMRS](https://arxiv.org/abs/2610.15579)
for dual-memory scheduling and [NetKV](https://arxiv.org/abs/2606.03910)
for network-aware D choice. A valid new mechanism must show a third-resource
network-stage decision that those baselines cannot match. The saturated
`Gain_upper` is unknown without an ordered burst and a correct two-sided
handoff; `SIMULATOR_UNSUPPORTED/NEED_DATA`, rather than a claimed gain.
If a cold 1–4P run shows exposed transfer, the earlier DAG/cut audit is
falsified and must be repaired before any policy test. Derivation:
[derive.py](derive.py).
