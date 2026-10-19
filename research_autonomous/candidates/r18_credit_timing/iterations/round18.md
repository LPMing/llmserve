# Round 18: early D credit holds capacity during Prefill

The profile-backed four-request threshold predicts 3,004 D blocks for
four 12k prompts and 3,504 for four 14k prompts, against a normal
3,400-block D pool. The negative 12k run admitted all four P jobs at
t=0 and completed at 2.882268 s. In the 14k run, the fourth P job
waited for credit until 3.113511 s, while D had no ready job for the
first 1.644666 s; its completion was 5.899737 s. Every request completed,
the 14k run conserved 7,340,032,000 P2D bytes across 896 flows, and
the event/path/block checks passed. This validates resource idling in
the **current early-credit protocol**, not a production prevalence claim.

`theory/optimistic_jit_bound.py` gives a conditional 4.401872-s fourth
completion if its P compute starts immediately, source KV is retained,
the first three D jobs finish unchanged, all bytes wait for credit and
the post-credit transfer pays only the 100-Gb/s serialization floor.
The 25.39% gap is against early credit and is an **analytic Oracle**.
An ordinary two-stage FIFO could plausibly attain the same gap, so the
increment over a strong baseline is unknown. The source-retention and
late-credit mechanism is not implemented or calibrated; this candidate
has an observed simulator-protocol mechanism but not an achieved gain.

Next discriminator: implement a bounded, correctly accounted source-KV
hold and late D credit under the same hardware and requests. Verify no
flow precedes credit, P blocks remain live until commit/cancel, D blocks
never exceed capacity, and all requests complete. Compare early-credit
FIFO against two-stage FIFO before trying SRPT/EDF or a new mechanism.

The source audit explains why a flag flip cannot provide this control.
`Scheduler._schedule_waiting()` obtains the current credit before
admitting the first P chunk; the Prefill trace then embeds the layerwise
P2D SEND nodes. `Scheduler.add_done()` frees P blocks and retires the
request as soon as that graph completes; the main loop transfers the
request to Decode, where `add_decode()` commits the prior reservation.
A valid late-credit comparison must split Prefill compute from its
transfer stage and keep source blocks owned between those stages.
Simply dropping the early credit would permit flows to reach a full D
pool before admission and reproduce the Round-16 invalid protocol.
