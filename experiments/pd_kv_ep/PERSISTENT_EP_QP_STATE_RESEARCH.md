# Persistent EP-QP DCQCN State Research

## Verdict

**Bounded result: `NO_TARGET_CNP_UP_TO_K4_STOP`.** In the tested model-derived
1P+2D / EP16 / 200-Gb/s packet-replay envelope, a P2D burst did not mark the
tracked EP QP with ECN, did not cause that QP to receive a CNP, and did not
reduce its DCQCN rate. Consequently, these runs do **not** demonstrate the
causal chain “P2D congestion → reduced persistent EP-QP state → later
post-queue EP slowdown.” The search stopped at the prescribed K4 bound; it was
not extended with larger traffic, lower link rates, smaller buffers, or altered
DCQCN parameters.

This is a no-go for the proposed mechanism **under this tested operating
envelope**, not a proof that a QP which has naturally received a CNP can never
retain a reduced rate in another runtime or deployment. The prerequisite state
transition was never activated here. No TTFT, TPOT, TBT, or SLO result is
available: this is a packet-level network replay with no completion feedback to
the serving scheduler.

The aligned K2 run did show a transient collective-tail increase, but it was
unchanged with DCQCN disabled and with fresh EP QPs. Its last-completing peer
was not the tracked rank16→rank8 peer. It is therefore **not evidence of
persistent DCQCN state amplification**.

## Hypothesis

The tested hypothesis was that one model-derived P2D burst could create a
shared-fabric congestion episode, mark an active Decode EP packet, deliver a
CNP to that packet's own persistent EP QP, lower that QP's rate, and leave later
EP rounds slower after the P2D-associated queue had returned to its EP-only
background envelope.

KV and EP used separate QPs throughout. No KV congestion state was copied into
an EP QP. The only proposed causal bridge was shared packet-network congestion
marking of an EP packet.

## Runtime grounding

The preceding runtime audit identified long-lived EP peer connections in
NCCL/DeepEP V2 as a plausible real-runtime behavior. That is motivation for
testing QP persistence, not proof that every deployment retains one RoCE QP per
logical rank pair or that its exact lifecycle matches this replay. The native
ns-3 experiment below verifies the *simulator mechanism and its controls*; it
does not validate a particular production NCCL/DeepEP QP mapping.

The implementation/source lifecycle audit is in
[`PERSISTENT_EP_QP_SIMULATION_AUDIT.md`](PERSISTENT_EP_QP_SIMULATION_AUDIT.md).
In brief:

- `entry.h::send_flow()` uses a persistent source-port map only for recurrent
  EP peer messages. P2D KV stays on fresh, independent QPs.
- `RdmaHw::AddQueuePair()` reuses an existing sender QP keyed by destination
  address, source port, and priority group; logical message callbacks and
  sequence boundaries are queued on that QP.
- The QP object holds the DCQCN rate, alpha, CNP flags, and recovery timers.
  Persistent `QpComplete()` retires one logical message without deleting the QP
  or cancelling those timers. Fresh QPs follow the ordinary deletion path.
- The switch receiver accumulates ECN feedback for a QP; an ACK can carry the
  CNP indication back to the sender. `RdmaHw::ReceiveAck()` then dispatches the
  feedback to the matching sender QP.

The QP reuse path and identity were exercised. The reduced-rate state-retention
path was not dynamically exercised because no tested run generated a CNP or a
rate transition.

## Current simulator limitation and scope

This is **network-only native ns-3 replay**. It replays model-derived
communication events and observes packet completion, queue telemetry, ECN/CNP,
and QP rate events. It does not return packet completion to LLMServingSim's
request scheduler. In particular, it cannot establish serving-level TTFT,
TPOT, TBT, or SLO impact.

The replay uses a controlled timing alignment for K2: only the release time of
the selected layerwise P2D event slice is shifted to the first rank16→rank8 EP
peer issue. Request identities, model-derived bytes, destinations, packet
payload, topology, and EP message ledger are unchanged. This is a mechanism
characterization alignment, not a production-arrival claim.

## Persistent-QP implementation and correctness

The optional simulator change is limited to recurrent EP messages. KV remains
fresh-QP traffic, so any EP state change would have to result from an EP packet
being marked while sharing a physical queue—not from state sharing between KV
and EP.

Correctness evidence:

- **Persistent identity: PASS.** In the aligned K2 persistent run, the tracked
  rank16→rank8 EP peer reuses source port `10002` and QP ID `27` across its 23
  messages. Its per-message `QP_START` samples all report 200 Gb/s.
- **Completion accounting: PASS.** Accepted runs have matching communication
  START/END event IDs. The aligned persistent K2 run completed all 1,796
  communication events.
- **Fresh-QP control: PASS.** The aligned K2 fresh-QP run assigned a distinct
  source port/QP to each tracked peer message; each starts at 200 Gb/s.
- **Reduced-state carry-over: NOT EXERCISED.** There is no CNP or RATE event in
  the target QP trace, so state persistence after an actual rate decrease
  cannot be measured from these runs.

The replay's QP identity and CC source audit is detailed in the linked
simulation audit, including source files and function locations.

## DCQCN and switch configuration

All parameters below are **simulator configuration**, not claims about
production-switch defaults. The 200-Gb/s egress uses `KMIN_MAP=600`,
`KMAX_MAP=2400`, `PMAX=0.2`; the MMU multiplies the first two by 1,000, so
Kmin is 600,000 bytes and Kmax is 2,400,000 bytes. Configured switch buffer is
32 MiB. Queue group 0 is exempt from ECN marking; data queues remain eligible.
ACKs use the high-priority control queue.

The runs use `CC_MODE=1`, 4-µs rate-decrease interval, 1-µs alpha interval,
900-µs RP timer, EWMA gain 0.00390625, 50/100-Mb/s additive rates, and
100-Mb/s minimum rate. The first-CNP rate multiplier remains the source default
1.0. No DCQCN equation, timer, threshold, link rate, or buffer size was tuned
for this experiment. The matched no-feedback runs use `CC_MODE=0`.

## Baseline EP rounds

The selected model-derived replay slice contains 45 collective groups and
1,792 EP flows per accepted run. The tracked rank16→rank8 peer is recurrent;
its median issue period is about 117 µs. EP-only baselines were collected at
the corresponding D8K1, D8K2, and D8K4 points.

| EP-only point | Mean CCT | P50 | P95/P99 | Groups |
|---|---:|---:|---:|---:|
| D8K1 | 27.549 µs | 22.149 µs | 33.330 µs | 45 |
| D8K2 | 27.593 µs | 22.149 µs | 33.656 µs | 45 |
| D8K4 | 27.695 µs | 22.149 µs | 33.821 µs | 45 |

Quantiles use nearest-rank statistics. With only 45 collective groups, P99 is
the sample maximum; it should not be interpreted as a well-estimated
production tail.

## Congestion episode and shared path

The topology is 1 Prefill + 2 Decode servers, EP16, one ToR, and six separate
200-Gb/s server NIC links (two NICs per server, four logical GPU ranks per
NIC). The selected EP path rank16→rank8 is `28→30→26`; the P2D path is
`24→30→26`. Both traverse directed ToR→D0 link ID 59 (`30→26`). The paths are
therefore genuinely shared; the negative ECN result is not explained by
topology separation.

The source workload is Qwen3-30B-A3B-Instruct-2507, EP16, model-derived routing
and bytes, LAYERWISE semantics, input length 8,192 tokens per new K request,
with the layer-2 P2D event slice replayed. The per-request slice is 4 MiB; it
is **not the full request's all-layer handoff**. `K1/K2/K4` therefore replay
4/8/16 MiB respectively, in 2/4/8 model-derived shard flows. The background
has eight active Decode requests. All runs retain the same 200-Gb/s fabric and
4-KiB packet payload.

| K point | P2D bytes | P2D flows | Max queue on shared 30→26 | Max queue any link | Kmin crossed? | ECN/CNP/RATE |
|---|---:|---:|---:|---:|---|---:|
| K1 | 4 MiB | 2 | 120,212 B | 120,212 B | No | 0 / 0 / 0 |
| K2, aligned to R0 | 8 MiB | 4 | 252,436 B | 252,436 B | No | 0 / 0 / 0 |
| K4 | 16 MiB | 8 | 24,792 B | 33,056 B | No | 0 / 0 / 0 |

All maxima are below the configured 600,000-B Kmin. K4's lower target-link
queue than K2 is due to model-derived P2D destination/path distribution across
the two Decode servers; request count and total bytes do not imply monotonic
load on the particular directed cut. No packet was ECN-marked on any link,
there were no CNPs or rate changes on any QP, and there were no PFC pauses or
drops.

The aligned K2 P2D slice started at 67,226.224 µs, matching the first tracked
EP peer issue (R0), and its last shard completed at 67,594.333 µs. The sampled
queue returned to the EP-only maximum envelope of 20,660 B at 67,594.808 µs,
0.475 µs after the last completion; that sample was 48 B, not an assertion of
an exactly empty queue. The P2D first-issue-to-envelope-return span was
368.584 µs, about 3.15 tracked EP periods. Thus the desired stricter alignment
`queue clear < R1 start` was **not** achieved: the P2D slice overlapped several
EP rounds. The later rounds after envelope return are still useful as
post-queue observations, but they do not turn this into a single-round,
R0-only congestion episode.

## Matched run results

| Point / run | CC | EP QP | Mean CCT | P99 CCT | Paired mean slowdown | Paired max slowdown | Post-envelope groups ≥10% |
|---|---:|---|---:|---:|---:|---:|---:|
| K1 EP-only | 1 | Persistent | 27.549 µs | 33.330 µs | — | — | — |
| K1 full | 1 | Persistent | 27.762 µs | 36.739 µs | +0.85% | +21.43% | 0/39 |
| K2 EP-only | 1 | Persistent | 27.593 µs | 33.656 µs | — | — | — |
| K2 full, original timing | 1 | Persistent | 28.365 µs | 43.799 µs | +2.79% | +36.89% | 0/36 |
| K2 aligned full | 1 | Persistent | 28.354 µs | 43.693 µs | +2.74% | +36.41% | 0/38 |
| K2 aligned full | 0 | Persistent | 28.354 µs | 43.693 µs | +2.74% | +36.41% | 0/38 |
| K2 aligned full | 1 | Fresh per message | 28.361 µs | 43.693 µs | +2.77% | +36.41% | 0/38 |
| K2 P2D shifted outside EP overlap | 1 | Persistent | 27.593 µs | 33.656 µs | 0.00% | 0.00% | — |
| K4 EP-only | 1 | Persistent | 27.695 µs | 33.821 µs | — | — | — |
| K4 full | 1 | Persistent | 27.723 µs | 34.132 µs | +0.09% | +0.92% | 0/30 |
| K4 full | 0 | Persistent | 27.723 µs | 34.132 µs | +0.09% | +0.92% | 0/30 |
| K4 full | 1 | Fresh per message | 27.723 µs | 34.132 µs | +0.09% | +0.92% | 0/30 |
| K4 P2D shifted outside EP overlap | 1 | Persistent | 27.695 µs | 33.821 µs | 0.00% | 0.00% | — |

The K2 raw P99 ratio is `43.693 / 33.656 − 1 = +29.8%`. The separate
`paired max slowdown` is the maximum of per-collective matched ratios and is
36.41%; these are different statistics. In both cases, the matched control
results show that the transient CCT increase is not DCQCN memory: K2 full is
identical under `CC_MODE=0`, and the fresh-QP control retains the same P99 and
the same worst paired slowdown. Shifting P2D outside the EP overlap restores
the EP-only distribution exactly.

## Queue-clear timestamp and QP recovery trace

For K2, the reported “clear” is the first sampled time after the last P2D
completion when link 30→26 is no higher than its EP-only maximum queue envelope
(20,660 B). It is an **excess-over-background envelope** definition, not a
packet-level proof that every queue in the topology is empty. The 1-µs
sampling interval and the 48-B sample are retained in the interpretation.

`EP_QP_RECOVERY_TRACE.csv` contains 299 tracked-peer records, all `QP_START`
samples. It contains **zero CNP and zero RATE events**, so `t_ECN`,
`t_CNP_receive`, `t_rate_decrease`, `t_full_recovery`, and recovery crossings
for 50/75/90/95/99% are not observable and are left unavailable—not filled
with zero. The tracked persistent K2 QP starts every message at 200 Gb/s. A
recovery timescale cannot be measured when no down-rate transition occurred.

For that reason, the requested inequality
`T_queue << T_EP_period < T_QP_recovery` cannot be tested. We observed an
EP-period-scale P2D-associated backlog span, but no QP recovery interval.

## Post-queue EP rounds and last-peer attribution

In K2, 38 collective groups began after the shared-link queue sample had
returned to the EP-only envelope. None had a positive matched slowdown in the
persistent run; none reached 10%. The fresh-QP control's maximum post-envelope
paired deviation was below 1% (0.99%), while the persistent run was 0% at the
CSV precision. K4 likewise had no post-envelope round with 10% slowdown.
These are post-queue CCT observations, **not** evidence of recovery from a
reduced DCQCN rate, because no rate decrease ever occurred.

The K2 worst paired slowdown is collective `40000322` (EP_DISPATCH): 30.214 µs
versus its matched 22.149-µs baseline, +36.41%. Its last peer is rank10→rank23,
path `26→30→29`, directed links `58;65`; the tracked rank16→rank8 peer is not
the last peer. The largest absolute K2 CCT is collective `40000363`
(EP_COMBINE), 43.693 µs, with last peer rank9→rank20 on the same D0→ToR→D1
direction. Thus neither tail collective is barrier-limited by the tracked
rank16→rank8 QP.

K2 full transmitted 98,304 more bytes on D0→ToR link 26→30 than its EP-only
baseline; K1's delta was 49,152 B. Reverse-path P2D ACK traffic is a plausible
contributor: the forward P2D path terminates at D0 and its ACKs traverse D0's
uplink, which is also on the last EP peer's route. The current link summary is
not per-packet ACK attribution, so this remains a mechanism hypothesis, not a
proven causal decomposition. K2's shifted-P2D run has the same reverse-link
byte delta but no CCT slowdown, consistent with timing overlap mattering.

`P(last peer QP was rate-reduced)` is zero in the measured sample because no
QP was rate-reduced. Conditional slowdown by reduced/not-reduced last-peer
state is therefore not estimable; it must not be reported as a nonzero or
zero-probability population claim.

## Controls

- **CC off:** aligned K2 and K4 CCT statistics and per-collective K2 tail match
  the CC-on persistent runs. This rules out DCQCN state as the explanation for
  the observed CCT tail.
- **Fresh EP QP:** aligned K2 fresh-QP CCT has the same P99 and worst matched
  slowdown as persistent-QP. K4 likewise matches. There is no persistent-QP
  advantage or penalty to attribute without a CNP/rate decrease.
- **Shifted P2D:** K2 shifted outside EP overlap is exactly EP-only in CCT and
  has no target-peer overlap. This supports a timing-dependent transient
  interaction, but not a post-queue state effect.

## Timescales

| Quantity | Observed value | Interpretation |
|---|---:|---|
| Tracked EP issue period | 117.022 µs (K1/K2 median) | Recurrent peer-message interval |
| K2 first issue → last P2D completion | 368.109 µs | Model-derived layer-slice replay span |
| K2 first issue → return to EP-only queue envelope | 368.584 µs | Sampled excess-backlog envelope span |
| Last completion → envelope return | 0.475 µs | 1-µs telemetry sample; 48-B queue sample |
| DCQCN state recovery | Not observed | No CNP or rate reduction occurred |

Because the K2 burst overlaps roughly 3.15 EP periods and the DCQCN state never
left line rate, this run does not satisfy the target temporal chain. Later
rounds are normal, but the experiment cannot distinguish “fast recovery” from
“no reduction was triggered”; the telemetry establishes the latter.

## PASS / FAIL classification

The requested mechanism gate requires a target-QP CNP and rate reduction
before testing whether reduced state survives the queue. The observed sequence
stops at the congestion-marking prerequisite:

| Gate | Result |
|---|---|
| Shared directed path exists | PASS |
| EP persistent QP identity reuse | PASS |
| P2D data and EP share link 30→26 | PASS |
| Target EP QP receives ECN/CNP | **FAIL: zero marks/CNP through K4** |
| Target EP QP rate decreases | Not reached; zero RATE events |
| Queue clears before the immediately next EP round | **FAIL for aligned K2**; P2D span is ~3.15 periods |
| Later post-envelope EP slowdown ≥10% | No; 0/38 K2 groups, 0/30 K4 groups |
| Fresh-QP / CC-off remove a persistent-only effect | No persistent-only effect exists; controls match |
| Serving-visible TTFT/TBT | Not measured by this replay |

**Classification: `NO_TARGET_CNP_UP_TO_K4_STOP`; bounded no-go for persistent
DCQCN state amplification in this model-derived 1P+2D operating envelope.**
This is not the stronger conditional claim “a naturally reduced persistent QP
never slows a later round”: no run entered that reduced state. In practical
research terms the candidate is closed here, because reaching its necessary
trigger would require going beyond the prescribed K4 bound or altering network
parameters, both explicitly out of scope.

## Next step

Do not increase K, add requests, tune ECN/DCQCN thresholds, lower link rate,
shrink the switch buffer, or force additional overlap to make a CNP appear.
Do not launch serving-feedback integration for this untriggered mechanism.
Preserve the result as a bounded negative characterization. If a future
independent runtime/production measurement establishes a naturally occurring
EP-QP CNP with persistent rate reduction, that would justify a *new* targeted
validation; the current simulation does not.

## Reproducibility artifacts

- Configuration and implementation audit:
  [`PERSISTENT_EP_QP_SIMULATION_AUDIT.md`](PERSISTENT_EP_QP_SIMULATION_AUDIT.md)
- Consolidated 13-run summary:
  [`PERSISTENT_EP_QP_EXPERIMENTS.csv`](results/persistent_ep_qp/PERSISTENT_EP_QP_EXPERIMENTS.csv)
- Matched per-collective/last-peer results:
  [`EP_PERSISTENT_QP_BASELINE.csv`](results/persistent_ep_qp/EP_PERSISTENT_QP_BASELINE.csv)
- QP state samples:
  [`EP_QP_RECOVERY_TRACE.csv`](results/persistent_ep_qp/EP_QP_RECOVERY_TRACE.csv)
- Analyzer:
  [`analyze_persistent_ep_qp_replay.py`](scripts/analyze_persistent_ep_qp_replay.py)
- Replay preparation/alignment tool:
  [`prepare_persistent_ep_qp_replay.py`](scripts/prepare_persistent_ep_qp_replay.py)
- Per-run raw packet, queue, CC, flow, and manifest files are under
  `results/persistent_ep_qp/runs/<run_name>/`.
