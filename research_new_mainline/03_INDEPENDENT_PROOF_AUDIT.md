# Independent proof/calculator audit

## Purpose

This is a small mathematical consistency check, deliberately independent of FlowSim, ASTRA-Sim, Serving callbacks, and project bandwidth-allocation helpers. It does not simulate a model or a real topology.

## Reference scheduler

`reference_owner_scheduler.py` enumerates the integer-time state graph for two/any small number of owners. State consists of remaining forward-link dispatch work, owner-GPU compute state, and remaining reverse-link combine work. Each tick can serve one ready dispatch owner and one ready combine owner simultaneously (full duplex); each owner's compute advances on its own exclusive GPU once its dispatch is complete. A combine is eligible only after its owner's compute is complete. Memoized exhaustive recursion chooses the owner served on each directed link. The model assumes zero propagation/startup/kernel overhead and allows network preemption at every tick; these make it an idealized reference, not deployment behavior.

The lower bound includes per-owner dependency chain, total work on each shared directed link, and the slowest GPU task. The bulk schedule serializes each direction's phase, runs all owner computes after dispatch, and completes after all combine work. The script asserts `T_lb <= T_exact <= T_bulk` for every case.

## Results (abstract ticks)

| Case | Dispatch | Compute | Combine | LB | Exact streaming | Bulk | Bulk−exact |
|---|---:|---:|---:|---:|---:|---:|---:|
| Cross-owner positive toy | 6,2 | 1,6 | 2,5 | 13 | 15 | 21 | 6 |
| Single-owner-dominant negative toy | 8,1 | 6,1 | 4,1 | 18 | 18 | 20 | 2 |
| Symmetric toy | 3,3 | 4,4 | 2,2 | 9 | 12 | 14 | 2 |

The positive witness has a different owner dominating dispatch/compute/return. The near-negative has almost all work on the same owner and little headroom. The symmetric case has no owner-ordering distinction but still gets ordinary phase overlap. This distinction matters: “no differentiated owner urgency” is not equivalent to “no generic pipelining gain.”

## Bound interpretation

For the positive toy, `H_optimistic = T_bulk - T_lb = 8` ticks, while exact idealized scheduling only saves 6 ticks. Thus the path/resource lower bound is properly optimistic. These integer durations are proof fixtures only; no conversion to microseconds is valid.

## Limits

- One abstract cut per direction, not a multi-hop Clos network.
- No per-flow propagation, packetization, startup, queue discipline, or rate changes.
- No shared-NIC multiplexing beyond the single link resource.
- Compute is unsplit; no partial expert profiles or launch penalties.
- No token-level top-k graph; each owner produces one aggregate result.
- No scheduler/admission feedback or TTFT/TBT.

Accordingly, this verifies the math/reference implementation only. It cannot pass the Qwen profile-based theory gate.

