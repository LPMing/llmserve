# Network-induced Decode KV-length skew and rebatching

**New hypothesis and data.** Asynchronously delivered P2D requests may
join an active Decode batch at heterogeneous KV lengths; separating one
long request could shorten the shared attention kernel. Qwen3-32B TP2
RTX PRO 6000 dense, attention and skew measurements are A; an arrival
mixture that creates the skew is C and remains unobserved. KV size is
262,144 B/token aggregate or131,072 B/TP rank. A 16k-token outlier adds
2.147 GB aggregate KV versus a 0-token request; on two 200-Gb/s rails its
P2D serialization floor is42.95 ms if cold, but it may already be resident
at D. The candidate optimizes Decode compute after admission, so P2D FCT
cannot be counted as an achieved gain. Its critical path is P2D-ready →
D admission → full mixed Decode iteration → token 2/ITL/completion.

**Profile-validity finding.** Historical `skew.csv` recorded the **sum** of
three attention timing samples per shot, whereas `attention.csv` averaged
them. Across330 exact pure endpoints, `t_max(skew)/t_uniform(attention)` has
median3.004. The ratio `alpha=(skew−mean)/(max−mean)` remains dimensionless
when the shot count matches within a row; raw old skew microseconds are not
per-layer costs. The profiler is now fixed for future shots, while historical
CSV files remain untouched. The simulator's existing alpha+uniform lookup
is the basis of [derive.py](derive.py).

**Bound and strong baseline.** At 0.9 utilization, TP2 has457,824 KV tokens
per rank. Of270 pure skew rows with `n≤128`, 21 exceed this runtime
capacity. Among249 feasible rows, the best *serial* length-bucket split is
still29.6% slower than keeping the mixed batch, because two batches repeat
all dense layers. Thus `Gain_upper<0` for serial rebatching; `NO_GO` before
simulating an invented arrival sequence. An ideal zero-skew kernel with no
extra dense work has at most11.31% over the stronger of mixed/split in a
rare feasible measured point, but that is an Oracle, not a scheduling gain.
The [vLLM HPC-Ops attention backend](https://github.com/vllm-project/vllm-project.github.io/blob/main/_posts/2026-07-06-vllm-hpc-ops.md)
already targets skewed attention kernels, so a multi-D placement variant
would need to beat both length-aware routing and that kernel baseline on a
real ordered load. Threshold/falsifier: show a feasible case where a legal
same-resource split reduces the *whole* iteration by≥10%; the current
measured profile falsifies that for serial splitting.
