# Heterogeneous Prefill/Decode tensor parallelism

**Scenario/data.** Qwen3-32B BF16 on RTX PRO 6000 96-GB GPUs has measured
TP1/TP2 profiles and exact model weights/KV sizes (A); 2048-token prompts,
600-token output and two independent 200-Gb/s rails are a bounded C
scenario. Full prompt KV is536,870,912 B. TP1 sends one536,870,912-B
shard on one source rail (21.475-ms floor); TP2 sends two268,435,456-B
shards on two rails (10.737-ms parallel floor). The converter conserves
bytes for asymmetric TP1↔TP2, but physical cut service depends on which
source/receiver NICs are present; no hypothetical extra rails are counted.

**Memory and compute threshold.** With 0.9 configured utilization, TP1
uses61.024 GiB weight/GPU and has103,936 KV tokens/GPU, at most39 active
2048+600-token sequences. TP2 uses30.513 GiB weight/GPU and has457,824
KV tokens/rank, so the128-sequence scheduler cap binds first. Measured
TP1 batch36 Decode step is63.202 ms, ~570 tokens/s/GPU. Even an
*infeasible but favorable* TP1 batch40 yields617 tokens/s/GPU. TP2 batch128
is53.524 ms, 2,391 tokens/s per two-GPU instance (~1,196/GPU). Thus two
TP1 Decodes offer at most51.6% of one TP2 Decode's profiled output rate
on the same two GPUs. Two TP1 Prefills can match one TP2's aggregate cold
Prefill capacity but worsen isolated prompt latency and source-rail demand.

**Strong baseline/Oracle/gate.** Compare the best fixed TP2 P:D ratio and
topology-aware pair choice with a hypothetical cost-free per-phase TP1/TP2
Oracle. In this long-output, memory-feasible envelope, the Oracle still
chooses TP2 for Decode and TP2 is no worse for the Prefill latency/cut;
`Gain_upper=0` for the proposed asymmetric reshape. TP/OTHER timing is
zero by default FlowSim, so this is a compute-only theory rejection, not a
positive absolute-latency claim. Falsifier: a model-matched real workload
with a measured TP1 per-GPU Decode advantage after correct memory and
collective costs. Derivation: [derive.py](derive.py). Status `NO_GO` here.
