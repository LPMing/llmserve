# Theory model and calibrated-input audit

## Bulk and streaming equations

For owner `i`, measure all times relative to a layer's common start:

- `d_i`: completion time of all dispatch inputs required by owner `i` under the specified network service model.
- `c_i`: that owner's unsplit expert-compute duration on its GPU.
- `r_i`: completion time of all combine outputs required by the corresponding source/consumer barrier.

With three globally synchronized phases, an idealized bulk model is:

```text
T_bulk = max_i(d_i) + max_i(c_i) + max_i(r_i)
```

If each owner can proceed after its own required dependencies, a dependency-path lower bound is:

```text
T_chain = max_i(d_i + c_i + r_i)
```

It is not sufficient by itself. A valid optimistic bound must include compute and network resources:

```text
T_stream_lb = max(
    T_chain,
    max_gpu sum(compute work assigned to that GPU),
    max_directed_cut(work on cut / capacity),
    NIC/resource lower bounds,
    propagation/startup terms that every legal path must pay
)
H_optimistic = max(0, T_bulk - T_stream_lb)
```

The cut term is computed separately per directed cut and phase, using only bytes traversing that cut. A full-duplex reverse path is a different resource. Per-peer flow count is not a bandwidth model. `H_optimistic` is a relaxation bound, not realizable savings.

## What is computable from the current model/profile

The model config and profile are present and hash-bound. `moe.csv` provides full-task latency samples on the RTX PRO 6000, with domain `tokens=1..2048` and activated experts sampled from 8 to 128. Example full-task samples include 1 token/8 experts = 50.2297 µs, 2/8 = 56.1917 µs, 4/8 = 56.6397 µs, and 2048/128 = 1066.6 µs. The lookup is for the whole rank-level MoE task, not arbitrary partial expert/token tiles.

The trace-generator's default BALANCED policy computes equal per-rank `local_tokens` and equal `activated_experts`; it does not expose source→owner communication counts. The sample retained EP32 sidecars show 2 tokens/2 activated experts per rank—outside the profile's activated-expert domain. Extrapolating that profile to 2 activated experts would not be a conservative measured compute estimate.

The standard trace also uses AG/RS, whose approximate per-rank payload is not an exact sparse source→owner matrix. The dormant exact P2P converter requires `pair_matrix` and `ep_global_ranks`, but current Serving graph construction does not supply either. Consequently current source/profile artifacts do not jointly identify `d_i`, `c_i`, and `r_i` for an authoritative Qwen owner-level case.

## Why no Qwen numerical headroom is reported

The missing input is not just a convenient runtime knob. It determines the answer:

1. Source→owner counts decide which owner receives each token and therefore its dispatch/combine work.
2. Physical rank mapping and directed paths determine per-owner transfer service and shared-cut lower bounds.
3. The per-owner compute lookup requires the actual post-dispatch token/expert shape inside its measured domain.
4. A real partial-compute proposal would additionally need subtask profiles; none exist in the current profile bundle.

Filling these from a balanced synthetic matrix, uniform A2A, or an out-of-domain profile lookup would manufacture the requested upper bound. This audit therefore records `NOT_COMPUTABLE_FROM_CURRENT_AUTHORITATIVE_INPUTS`, rather than a guessed percentage or a zero.

## Independent integer-time witness (not Qwen calibration)

`reference_owner_scheduler.py` models two owners, a unit-rate shared forward link for dispatch, an independent unit-rate reverse link for combine (full duplex), one exclusive GPU per owner, and integer-tick preemptible network service. It computes the exact best schedule by dynamic programming over small states and verifies `lower_bound <= exact <= bulk`.

The positive abstract witness has `(d,c,r)=((6,2),(1,6),(2,5))`: lower bound 13 ticks, exact streaming 15, bulk 21, ideal exact gap 6 ticks (28.6% of bulk). The single-owner-dominant negative has `((8,1),(6,1),(4,1))`: lower bound/exact 18 and bulk 20, leaving only 2 ticks (10%). These prove the equation can express positive and near-negative cases; they are not model-derived bytes, compute times, or paper motivation.

