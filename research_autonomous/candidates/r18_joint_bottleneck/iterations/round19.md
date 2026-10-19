# Round 19: network-order control after two-stage FIFO

The theory card predicted that FAIR shares three simultaneous 1.835-GB
flows, delaying their first Decode-ready event, while a work-conserving
FIFO tie-break could finish one earlier and release D capacity for the
fourth held source. This was tested on the same four14k/64 workload,
4P1D resource set and correct two-stage FIFO as B. `KV_REQUEST_FIRST
id0` was an offline FlowSim control; id0 is a lawful equal-arrival FIFO
tie-break in this exact stream. It is not an online general-purpose
policy implementation.

The control passed 7,340,032,000 B, four completions, D block and
source-lifetime/event/path checks. Last completion was 4.515045840 s,
versus FAIR's 4.842297960 s: 6.76% modeled gain. The result supports
the causal order (early first ready -> earlier Decode completion ->
earlier fourth credit), but it is below the 10% screen **and already
available to a simple FIFO network order**. It does not establish a
joint-policy failure or a legal global Oracle gap.

Decision: `NO_GO` for C's current uniform fixture as a paper case.
Further C work should start from a source-backed heterogeneous co-arrival
distribution and derive a legal same-resource upper bound **against**
FIFO/SRPT network order, capacity-aware admission and cache/load-aware
routing before any new policy run. Changing link speed or memory solely
to create a positive result is prohibited.

An unchanged first-50-request window from the committed Llama ShareGPT
trace was screened next, before a Serving run. Its full-KV cut service is
only0.492380 s before DELTA, while the last request's own profiled
minimum Decode work after arrival forces completion no earlier than
15.996 s. Their3.078% ratio is conditional on fixed downstream work;
it is not a valid upper bound for a joint policy changing batching or
memory. Because this screen does not produce a >=10% strong-baseline
opportunity, no extra source-backed simulation was run merely to seek a
positive network result. Script, hashes and result are in `theory/`.
