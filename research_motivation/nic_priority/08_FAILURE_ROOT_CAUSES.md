# Why the campaign did not show a new fine-grained scheduling opportunity

## 1. Layerwise KV delay is hidden by producer slack

P2D sends each layer's KV after that layer's QKV work, while later Prefill
layers continue. The request barrier waits for the last required shard, but
the observed post-final-release drain is only 0.77–1.19 ms. The policy-induced
delta is around 6–9 us and does not move Decode readiness or TTFT in the
recorded CSV. Thus a large total transfer duration does not imply that all
of it lies on TTFT's exposed critical path.

## 2. The EP-vs-KV theoretical byte/time budget is small

The recurrence communicates about 1.03 MB per EP4 token per receiving rail,
versus the continuous P2D stream. Even under the deliberately generous
fully-exposed 48-layer serialization bound, cross-class interference is
about 93 us/token, roughly 1.58% of a 5.876-ms seed TBT. Measured FAIR to
EP_FIRST mean TBT improvement is 0.61%; P99 does not move. A much larger
result would require another validated mechanism, not just renaming this
budget.

## 3. Class priority already captures the tested opportunity

KV_FIRST is pathological for recurrent EP in this particular class-arbitrated
model, but EP_FIRST restores the Decode barrier close to the isolated control
while leaving candidate KV TTFT unchanged. No within-KV or within-EP urgency
counterexample was measured. The evidence therefore does not establish an
incremental benefit for request-/collective-aware priority.

## 4. A second physical layer is not simulated

The observed queue is FlowSim's residual-fluid work, not a switch buffer or
RNIC queue. Packetization, ACK/CNP, DCQCN, PFC and hardware NIC arbitration
cannot be inferred from it. This is an evidence boundary, not proof that
packet effects do not exist.

## 5. Small, controlled sample and approximation of EP

There are eight independent seed requests, with token intervals correlated
within each request; candidate requests have one output token. EP traffic is
simulator AG/RS expanded into peer flows, not exact GateRouter A2A. No
multiple-seed uncertainty estimate or natural-arrival replay is provided.

## Not the explanation

The simulation is not GPU-compute executing the model. GPU profile timings
are inputs. A faster GPU profile changes modeled release/overlap/slack, not
wall-clock simulator execution. In this campaign each integrated run took
about 37–43 seconds wall time; the measured outcome does not indicate a
GPU-compute bottleneck.
