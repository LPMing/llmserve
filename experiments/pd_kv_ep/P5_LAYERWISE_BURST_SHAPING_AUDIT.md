# P5 Layerwise Burst Shaping Audit

## Decision

`P5_FINAL_FAIL_CURRENT_BACKEND_NO_TRANSPORT_GRANULARITY`

This is a semantic feasibility failure, not a negative performance result.
The direction is not run as a fabricated packet experiment.

## Why the current implementation cannot test P5

The model-derived replay builder creates a layerwise P2D event at the
model/serving release timestamp. `--max-flow-bytes` can split that event into
multiple flow records, but all pieces inherit the same `start_ns`; it is flow
decomposition, not NIC pacing, WQE scheduling, rendezvous protocol, or legal
transport chunk release. `--packet-payload-size` changes packetization only.

The current repository does not expose a NIXL/UCX/WQE/rendezvous transport
object that controls injection credits or burst timing. The native packet
replay therefore has no validated transport-level knob for “one immediate
transfer vs paced/chunked transfer” while holding the serving release and
bytes fixed. Adding such a knob solely to activate ECN/PFC would be an
unvalidated runtime model, contrary to the research gate.

## Evidence inspected

- `experiments/pd_kv_ep/scripts/build_model_derived_replay.py`: layerwise
  events and `max_flow_bytes` splitting.
- `serving/__main__.py`: `packet-payload-size` is a packet payload override.
- `serving/core/flowsim_worker.py`: FlowSim provides analytical fluid sharing,
  not packet transport burst semantics.
- Existing native packet reports: queue/ECN/DCQCN effects are retained, but
  no sender-side transport granularity is attached to a model release event.

The next valid direction is N1, which has an existing serving scheduler
boundary and can be tested without inventing a transport mechanism.
