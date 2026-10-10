# Persistent EP QP packet-replay audit

## Scope and result

This audit covers the optional persistent-QP mode used by the bounded native
ns-3 replay. The replay is a network-only event replay: it records packet-path
completion, collective CCT, QP congestion-control telemetry, and link queues. It
does not feed network completion back into the LLMServingSim scheduler, so this
test cannot produce valid TTFT, TPOT, TBT, or SLO results.

The code path now supports one long-lived sender QP per recurrent directed EP
peer while leaving P2D KV messages on fresh, independent QPs. In the completed
tests, identity reuse is verified, but no tested P2D case produced a CE mark,
CNP, or DCQCN rate reduction. Thus the *state-retention path is implemented*,
but this traffic did not activate a reduced state whose persistence could be
measured.

## QP creation and identity

The frontend `send_flow()` maps logical GPU ranks to physical NIC nodes, then
assigns the source port. With persistent EP enabled, the port-map key is
`(logical src rank, logical dst rank, priority group)`; the first message gets a
port from `portNumber[network_src][network_dst]`, and later messages for that
key reuse it. Only EP dispatch/combine events use this map. KV uses the ordinary
fresh-port path. The frontend passes the persistent flag through
`RdmaClientHelper` to `RdmaClient::StartApplication()` and then
`RdmaDriver::AddQueuePair()`.

The sender's QP lookup key in `RdmaHw` is `(destination IP, source port,
priority group)`. A repeated persistent `AddQueuePair()` finds that QP in
`m_qpMap`, appends a logical-message sequence boundary and callback to
`m_pending_messages`, and reuses the same QP object. The QP is reinserted into
the NIC QP group if normal completion scheduling had removed it. This supports
multiple outstanding logical messages on one transport QP without resetting
the cumulative sequence space.

On first creation, the QP receives a unique `qp_id`, records its logical source
and destination ranks, and initializes `m_rate` / DCQCN target rate from the
selected NIC's line rate. `RdmaQueuePair` initializes the DCQCN fields
(`m_alpha`, first-CNP flag, CNP flags, rate-increase stage and timer handles).
For a reused QP, this initialization path is not run again.

At message completion, persistent `QpComplete()` pops the acknowledged logical
message and restores its tag, byte count, start time, and callbacks for the
completion callback. It does **not** cancel the DCQCN alpha/decrease/recovery
timers and does **not** erase the sender QP from `m_qpMap`. The replay completion
callback also retains the receiver Rx-QP for persistent connections. Fresh QPs
take the existing deletion/timer-cancel path.

## Congestion feedback path

For `CC_MODE=1`, switch MMU ECN marking is evaluated per egress port and
priority queue. Queue group 0 is excluded from ECN marking; data in groups 1/3
remains eligible. For 200-Gbps links, this run's configuration sets
`KMIN_MAP=600`, `KMAX_MAP=2400`, and `PMAX=0.2`. The MMU converts Kmin/Kmax to
bytes by multiplying by 1,000, so the configured Kmin is 600,000 bytes and
Kmax is 2,400,000 bytes. The configured switch buffer is 32 MiB. These are the
simulator configuration values, not claims about a specific production switch.

The receiver accumulates ECN bits on its Rx-QP; an ACK carries the CNP flag when
the received data packet had ECN set. The sender's `ReceiveAck()` looks up the
matching sender QP and, on CNP, calls `cnp_received_mlx()`. A rate transition is
recorded through the `RateChange` trace. The telemetry file distinguishes
`QP_START`, `CNP`, and `RATE` events and records QP ID, source/destination rank,
source port, and old/new rate.

The DCQCN parameters used here are read from the generated `replay.conf`:

| Parameter | Value |
|---|---:|
| `CC_MODE` | 1 |
| `RATE_DECREASE_INTERVAL` | 4 us |
| `ALPHA_RESUME_INTERVAL` | 1 us |
| `RP_TIMER` | 900 us |
| `EWMA_GAIN` | 0.00390625 |
| `FAST_RECOVERY_TIMES` | 1 |
| `RATE_AI` / `RATE_HAI` | 50 / 100 Mb/s |
| `MIN_RATE` | 100 Mb/s |
| `L2_ACK_INTERVAL` | 1 |
| `ACK_HIGH_PRIO` | 1 |
| packet payload | 4,096 B |

`RateOnFirstCnp` is not overridden by this config; the source attribute default
is 1.0. The first-CNP path schedules the subsequent rate-decrease check. No
DCQCN equation, timer, threshold, or rate parameter was changed for this test.

## Topology and endpoint mapping

The packet topology is one Prefill server plus two Decode servers, one ToR, and
six independent 200-Gbps NIC uplinks. Each server has 8 logical GPU ranks and
two 200-Gbps NICs, with four GPU ranks mapped to each NIC. The NIC nodes are
P0=`24/25`, D0=`26/27`, D1=`28/29`; ToR is node `30`. The model-derived EP16
rank placement puts ranks 8–15 on D0 and ranks 16–23 on D1.

For the tracked peer, rank16→rank8 maps to path `28→30→26` and traverses
directed link ID 59 (`30→26`). The K2 P2D flows map to `24→30→26` and traverse
the same directed link ID 59. Thus the selected EP peer and KV data genuinely
share one physical directed egress. Other peer directions can use different
links; CCT attribution must therefore identify the actual last peer, not assume
the tracked peer is critical.

## QP correctness status

- **Identity reuse: PASS.** In the persistent baseline, the tracked rank16→rank8
  peer uses one source port and one QP ID across its recurrent messages. In the
  aligned K2 run, 23 messages use port 10002 and QP ID 27.
- **QP completion accounting: PASS.** The accepted replays have matching
  communication START/END event IDs; all messages complete.
- **Fresh-QP control: PASS.** The aligned K2 fresh control creates a distinct
  QP/source port for each tracked peer message, and each begins at the 200-Gbps
  line rate.
- **Reduced-state persistence: NOT EXERCISED.** The tested traffic never sends a
  CNP to the tracked QP and never emits a RATE event. The code retains the
  relevant object/timers, but there is no naturally induced down-rate state in
  these runs to carry into a later round.

## Source map

- Rank→NIC mapping, EP-only persistent source-port identity, KV fresh-port
  behavior, and helper propagation: [`entry.h`](/home/dell/lpm/LLMServingSim/astra-sim/astra-sim/network_frontend/ns3/entry.h:88)
- Client/helper handoff into the RDMA driver: [`rdma-client.cc`](/home/dell/lpm/LLMServingSim/astra-sim/extern/network_backend/ns-3/src/applications/model/rdma-client.cc:127), [`rdma-client-helper.cc`](/home/dell/lpm/LLMServingSim/astra-sim/extern/network_backend/ns-3/src/applications/helper/rdma-client-helper.cc:57), [`rdma-driver.cc`](/home/dell/lpm/LLMServingSim/astra-sim/extern/network_backend/ns-3/src/point-to-point/model/rdma-driver.cc:64)
- QP lookup/creation, line-rate initialization, persistent reuse, and deletion: [`rdma-hw.cc`](/home/dell/lpm/LLMServingSim/astra-sim/extern/network_backend/ns-3/src/point-to-point/model/rdma-hw.cc:236)
- QP congestion-state initialization: [`rdma-queue-pair.cc`](/home/dell/lpm/LLMServingSim/astra-sim/extern/network_backend/ns-3/src/point-to-point/model/rdma-queue-pair.cc:23), [`rdma-queue-pair.h`](/home/dell/lpm/LLMServingSim/astra-sim/extern/network_backend/ns-3/src/point-to-point/model/rdma-queue-pair.h:33)
- Receiver ECN accumulation/CNP-in-ACK and sender CNP handling: [`rdma-hw.cc`](/home/dell/lpm/LLMServingSim/astra-sim/extern/network_backend/ns-3/src/point-to-point/model/rdma-hw.cc:384), [`rdma-hw.cc`](/home/dell/lpm/LLMServingSim/astra-sim/extern/network_backend/ns-3/src/point-to-point/model/rdma-hw.cc:489)
- Persistent completion and DCQCN rate/recovery functions: [`rdma-hw.cc`](/home/dell/lpm/LLMServingSim/astra-sim/extern/network_backend/ns-3/src/point-to-point/model/rdma-hw.cc:605), [`rdma-hw.cc`](/home/dell/lpm/LLMServingSim/astra-sim/extern/network_backend/ns-3/src/point-to-point/model/rdma-hw.cc:725), [`rdma-hw.cc`](/home/dell/lpm/LLMServingSim/astra-sim/extern/network_backend/ns-3/src/point-to-point/model/rdma-hw.cc:773)
- ECN queue threshold and Kmin/Kmax byte conversion: [`switch-mmu.cc`](/home/dell/lpm/LLMServingSim/astra-sim/extern/network_backend/ns-3/src/point-to-point/model/switch-mmu.cc:100)
- Run configuration: [`replay_template_dcqcn.conf`](/home/dell/lpm/LLMServingSim/experiments/pd_kv_ep/configs/ns3/replay_template_dcqcn.conf:18)
- Replay is explicitly network-only: [`run_model_derived_replay.py`](/home/dell/lpm/LLMServingSim/experiments/pd_kv_ep/scripts/run_model_derived_replay.py:1)
