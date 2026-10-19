# Round 19: two-stage FIFO closes the admission-only gap

## Hypothesis and falsifier

Early D credit pins receiver capacity throughout a 1.645-s Prefill.
Two-stage FIFO may run all four 14k Prefills immediately, hold each
source KV, then acquire credit and send. The falsifier was byte, capacity,
source-ownership or cancellation failure, or a residual >=10% gap to a
same-resource admission-only Oracle. The model has 131,072 B/KV token:
each 14k request sends 1,835,008,000 B, requires 876 D blocks, and
four credits require 3,504 > 3,400 blocks. The declared 100-Gb/s cut
has a 587.203-ms four-flow serialization floor, before overlap.

## Repair and verification

An opt-in `TWO_STAGE_FIFO` now runs Prefill as a compute-only graph,
retains source KV after computation, queues the request in FIFO order,
acquires D capacity before a transfer-only graph, and releases source
KV only after its graph completes. An internal cancel of a held request
releases source blocks immediately; an in-flight cancel waits for graph
completion, then releases both source blocks and receiver reservation.
The simulator has no external cancellation workload/API, so this tests
state-machine semantics rather than a production cancel handshake.

The first transfer-only attempt `prompt_14000_two_stage_fifo_r19a`
overcounted bytes eightfold: `fp=16` bits was treated as 16 bytes. Its
raw outputs and `analysis.json` are retained as `INVALID_BYTE_OVERCOUNT`;
`fp//8` fixed the trace before any performance comparison. A model-byte
unit test covers BF16 and FP8. The actual block-pool cancellation tests,
all 52 P/D tests and 11 focused simulator tests pass. The matched
analyzer validates per-flow rank, physical rails, exact bytes, credit,
source release and modeled Serving event order.

## Same-workload results

| Stream | Early POST last completion | Two-stage FIFO | Simple FIFO gain | Admission-only Oracle lower bound | Residual FIFO gap |
|---|---:|---:|---:|---:|---:|
| Four 14k/64 at t=0 | 6.486961960 s | 4.842297960 s | 25.3534% | 4.842285760 s | 0.000252% |
| Ordered `(12k,32,0)`, `(14k,96,.2)`, `(14k,48,.4)`, `(16k,64,.6)` | 5.310646680 s | 4.112784320 s | 22.5559% | 4.112784320 s | 0% |

Every valid arm sends exactly 7,340,032,000 B on the same source cut.
For the uniform stream all P computations start at zero in the two-stage
arm; the fourth credit waits until the first Decode completion, then its
transfer begins. The heterogeneous stream admits each P at arrival,
has four distinct Prefill and Decode jobs, and also matches the scoped
admission Oracle. These are modeled request-completion gains of an
ordinary baseline over the old early-credit protocol. They are **not**
new algorithm gains. The Oracle is conditional on fixed FAIR network and
FIFO Decode, not a global scheduling lower bound.

We then reran the **stronger early layerwise** protocol on the current
code with the same two streams and resource map. It overlaps KV sends
with Prefill and emits 896 smaller flows, still exactly7,340,032,000 B.
Uniform last completion was5.899737000 s; heterogeneous was5.020136000 s.
The simple two-stage FIFO is17.9235%/18.0742% faster than those stronger
early arms. This is a whole-protocol comparison because layerwise and
post-P transfer DAGs differ; the EARLY_POST pair above isolates the
credit-timing change. It does not create an extra new-policy gap over
two-stage FIFO.

## Decision

`NO_GO` for B as an admission-timing paper on these fixtures: the strongest
simple two-stage FIFO closes essentially all scoped space. The observed
early-credit idling mechanism remains valid as a simulator/protocol
finding. A separate network-order control belongs to C, not B.
