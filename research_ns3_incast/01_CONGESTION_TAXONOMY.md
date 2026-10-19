# Congestion mechanisms audited for this study

Status labels distinguish packet evidence from previous analytical/FlowSim
evidence. FlowSim backlog is fluid/analytical state, not a packet queue.

| Mechanism | Physical resource and necessary pattern | Service-time reason | Current evidence/status | Serving barrier / optimization implication |
|---|---|---|---|---|
| Receiver-side KV incast | Multiple source NICs send to one 200G Decode NIC egress | Receiver cut has aggregate arrival above 200G; queue forms until the simultaneous burst drains | **Packet PASS:** N1 two→one, N2 four→one; local CE on Decode leaf→NIC | Per-flow FCT and a fixed-event request barrier increase. In the profiled LAYERWISE case, all waves drain before Prefill compute ends, so this queue is hidden from the Decode-admission barrier. |
| Sender-side shared NIC | Several GPU ranks sharing one source NIC uplink | Sum of active sender rates exceeds one shared 200G uplink | **Not isolated in this gate.** One active P rank per source NIC; source NIC is not the contested cut | Requires multiple simultaneously active GPU ranks behind the same source NIC and request/barrier attribution. Do not infer from receiver incast. |
| Synchronized Prefill KV bursts | Model layer/chunk completions from multiple Prefill instances align | Short aggregate burst exceeds receiver egress; queue is then drained during inter-layer slack | **Packet PASS:** 96 profile-derived release cohorts. CC0 min inter-wave completion slack 959.943µs; CC1 55.255µs; no wave overlaps the next release | Queue/ECN repeats, but current final P2D readiness remains before profiled Prefill end. A signal could matter only if a different legal profile/load removes that slack. |
| KV–KV | Distinct requests' KV shards converge on same receiver NIC | Shared receiver serialization; max-shard barrier follows the latest required destination shard | **Packet PASS:** N1/N2 and FULL4; N2 request readiness ≈32.48ms under simultaneous release | A fixed release-order/pacing baseline can improve mean readiness, but does not improve makespan here. No feedback-driven Serving gain established. |
| KV–EP shared cut | P2D KV and Decode EP share a directed physical link/egress at overlapping times | Queue/service sharing can delay a critical EP peer or KV last shard | **Not run in this receiver-incast packet gate.** Historical FlowSim results are analytical and are not substituted for ns-3 | Requires exact EP group traffic and a common packet path. No current packet-level serving claim. |
| EP–EP collective concurrency | Two independent Decode groups issue legal overlapping collectives across a common cut | Collective completion is the max/last required peer; independent barriers can interfere | **Not run in this packet gate** | Must preserve group-wide barriers and actual physical flow ownership. No synthetic overlap is claimed. |
| ECN/CNP/DCQCN response | Queue crosses configured ECN threshold; CNP reaches the source QP and CC_MODE=1 adjusts rate | QP remains at reduced rate during the active message; future QP inheritance depends on QP lifetime | **Packet PASS within each QP:** CC1 produces CNP and RATE changes in N1/N2/FULL4 and LAYERWISE | Layerwise replay opens one QP per message/layer/shard, so rate state does not carry to the next event. It is not evidence about persistent-QP carryover. |
| PFC / priority HOL | A lossless-priority queue reaches pause threshold; pause propagates upstream | Sender can be blocked even when its own queue is eligible; HOL needs an actual blocked eligible packet/flow | **Not activated:** 32MiB buffer, max observed queue 3.149MB, zero PFC pauses/drops | This gate cannot support a PFC/HOL claim. ACK/control packets remain on the configured high-priority control queue. |
| External tenant cross-traffic | Independent background workload shares sender, receiver or fabric cut | Competing offered load consumes service and can alter CC state | **Not run** | Do not add synthetic background bytes to this result. Any future test needs a trace/provenance-backed load. |
| ECMP hash collision | Multiple flows hash onto a subset of equal-cost paths | A path cut becomes busier than aggregate topology capacity suggests | Main N2 excludes this with sender-specific spines. Multipath route audit observed all four flows choose the same spine (a collision), so it is **a collision control**, not a balanced-ECMP result | Incast exists without ECMP. N5 “balanced all paths” was not established; do not claim it. |

## What this taxonomy says

The packet-level evidence establishes receiver-NIC incast, repeated synchronized
KV bursts, and DCQCN response. It does not establish that congestion feedback
has a useful Serving action: the packet replay freezes the release ledger, and
the profile-derived LAYERWISE completion remains hidden by compute slack.
KV–EP and EP–EP packet interaction were not part of this gate.
