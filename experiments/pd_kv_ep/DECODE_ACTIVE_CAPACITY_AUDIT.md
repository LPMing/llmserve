# Decode active-sequence capacity audit

Audit scope: the checked-in 1P2D EP16 cluster configuration, current serving
defaults, current Qwen3 profile, and the workload's 128-input/128-output Decode
cohort. This is a simulator/configuration capacity audit, not a claim about a
deployed GPU runtime's measured capacity.

## Effective scheduler limits

- `configs/large_scale/minimal_1p2d_ep16_shared_400g.json` defines eight
  Decode instances. Each has `num_npus=2`, `tp_size=2`, and belongs to
  `dp_group=decode_ep`; the group has 16 EP ranks total. The config does not
  override `max_num_seqs` or `max_num_batched_tokens`.
- `serving/__main__.py::_build_instance_runtime_configs` takes per-instance
  values when present, otherwise the CLI values. CLI defaults are 128
  sequences and 2,048 batched tokens. `_runtime_limit(0)` means unlimited;
  this run does not set zero.
- `Scheduler._schedule_waiting` admits only while `len(running) <
  max_num_seqs`; `_schedule_running` consumes the same 2,048-token iteration
  budget. Thus the effective Decode cap is 128 active sequences **per Decode
  scheduler**, not 128 for the whole cluster and not 16 because EP degree is
  16.
- With the fixed eight Decode schedulers and RR P/D pairing, the configured
  aggregate cap is `8 x 128 = 1,024` active Decode sequences. The eight
  Prefill schedulers also have a 128-sequence cap, so they can admit the
  corresponding 1,024-request cohort before handoff. The new experiment does
  not change either default.

## Distinguishing EP, batch, and request counts

- EP16 is the 16-rank collective participant count.
- `D_active` is the number of distinct serving requests in the Decode cohort
  across the eight Decode schedulers.
- At D=1,024, balanced pairing yields at most 128 active requests per Decode
  scheduler. Each Decode iteration schedules one token/request, so the local
  Decode batch consumes 128 of the 2,048 token budget. No EP degree is being
  mislabeled as active request capacity.

## Memory bound for this exact request shape

The model config is 48 layers, 4 KV heads, `head_dim=128`; BF16 KV is 2 B per
element. The audited TP2 per-rank KV size is:

`2(K,V) x 4 x 128 x 256 tokens x 48 layers x 2 B / 2 TP ranks`
`= 12,582,912 B = 12 MiB per rank per 256-token sequence`.

The serving config assigns 96 GiB per GPU, with the CLI's 0.9 memory
utilization. Re-evaluating `MemoryModel.get_weight()` using this model, TP2,
and EP16 gives 5,177,741,312 B model weight per rank. The simulator therefore
allocates approximately 87,593,552,281 B (81.58 GiB) to the KV pool per rank,
or 111,380 16-token blocks. At the effective cap of 128 sequences per
scheduler/rank, KV occupancy is about 1.5 GiB per rank—well below the modeled
pool. The simulator's KV capacity is an upper bound because activation peak
and CUDA context are not subtracted.

For comparison, 256 sequences per rank would use about 3 GiB of KV and is
also below modeled memory capacity, but it is **not** this run's effective
scheduler configuration and is not needed to define the 1,024-sequence cap.

## Profile coverage / extrapolation

The matching bundle is
`profiler/perf/RTXPRO6000/Qwen/Qwen3-30B-A3B-Instruct-2507/bf16/`.
`meta.yaml` records `max_num_seqs=256`, `max_num_batched_tokens=2048`,
attention `n_decode` through 256, and `kv_decode` through 16,384. The TP2
attention table contains up to 256 decode sequences. Qwen MoE compute is
profiled at TP1 by design; its `moe.csv` covers token counts through 2,048
and activated-expert counts through 128. Under the unchanged cap, every
Decode scheduler's batch is at most 128 sequences and context at most 256
tokens, so the planned D<=1,024 sweep remains inside these tabulated ranges.

No profile extrapolation is required for these planned points. Any run whose
effective per-scheduler batch exceeds 256, whose attention KV length exceeds
16,384, or whose relevant MoE lookup exceeds its profile axes must be marked
`COMPUTE_PROFILE_EXTRAPOLATED` and is outside the present capacity verdict.

## Capacity verdict

`LEGAL_ACTIVE_DECODE_MAX = 1024` for the **current checked-in runtime
defaults and eight Decode schedulers**. The bound is scheduler admission,
not KV memory. The planned escalation is D32, D64, D128, D256, D512, D1024,
stopping earlier if shared-cut saturation or a serving-barrier result gives
the next experiment no information value.
