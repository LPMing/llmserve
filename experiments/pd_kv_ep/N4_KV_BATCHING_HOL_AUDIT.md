# N4 Cross-Request KV Batching / HOL Audit

## Status

`N4_FINAL_FAIL_NO_RUNTIME_KV_BATCHING_OR_HOL`

This direction cannot be evaluated faithfully by the current implementation.
The simulator has independent request/layer/shard KV events and a fluid
resource-sharing model, but no transport or runtime object that batches KV
requests, serializes them behind a shared head-of-line queue, or exposes a
batching policy.

## Hypothesis

An implementation may combine several small P2D or remote-KV transfers into a
shared operation. This could improve per-message overhead but also make a
short latency-sensitive request wait behind a large request, producing:

`cross-request KV batching -> HOL wait -> last-shard barrier -> TTFT tail`.

## Audit result

The serving path creates P2D communication from the scheduled request batch,
but the communication records remain request-scoped and layer/shard-scoped.
The relevant path is:

`serving/core/scheduler.py::_build_batch`
-> model-derived `pd_kv_send_tokens`
-> trace generation
-> `serving/core/flowsim_worker.py::_new_p2d_flow`
or `_attach_remote_kv_fetches`
-> one `FlowSpec` per communication event.

`FlowSpec` carries one event's bytes and provenance. Its `request_ids` tuple
can describe an aggregate event, but it does not implement a batching queue.
In the current P2D path, the generated P2D records are not cross-request
coalesced.

The only existing replay coalescing is:

`experiments/pd_kv_ep/scripts/run_flowsim_replay.py::_read_events`

with `--coalesce-ep-window-us`. It aggregates EP dispatch/combine rows by
time bucket, source, destination, and event type. KV rows are deliberately
retained at request granularity. This option is a bounded FluidSim memory
optimization/counterfactual for EP, not a runtime KV batching or HOL model.

`max_flow_bytes` similarly splits a model event into multiple same-start
flows. It does not add a release queue, message coalescer, WQE scheduler, or
transport serialization policy.

## Why no result was fabricated

Merging several KV rows in the event builder and assigning the merged row
multiple request IDs would destroy the individual request completion barrier.
Adding a delay to the smaller request would be an artificial HOL delay. Both
would change serving semantics rather than measure an existing mechanism.

## Decision

N4 is closed for the current simulator. To reopen it, the project would need a
validated runtime/transport model specifying batching eligibility, flush
conditions, maximum aggregate size, message ordering, and per-request
completion demultiplexing. Without those semantics, no CCF-level claim about
KV batching or HOL can be made from this repository.

