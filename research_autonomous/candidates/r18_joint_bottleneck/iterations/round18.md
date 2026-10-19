# Round 18: cross-candidate resource-boundary screen

The A fixture has a hot Prefill and full KV source-cut serialization
floor 2.048 times the hot-P compute; the measured final flow is on
the P2D-ready path. The B 12k/14k pair instead has NIC-floor/P-compute
ratios below 0.37, while the D block occupancy ratio crosses from
0.884 to 1.031. Its fourth P waits on a capacity credit rather than
the network cut. These are two different regimes, not evidence that a
joint scheduler beats simpler policies. A same-resource joint decision
and legal Oracle are still missing, so C remains at the theory gate.

The next C experiment requires a frozen heterogeneous request stream
with one P/D placement and fixed GPU/NIC/KV budget. First compare
FIFO, two-stage FIFO, SRPT/EDF and a simple multi-resource score; only
then compute a small legal Oracle. Do not count P:D reallocation as an
admission-policy gain.
