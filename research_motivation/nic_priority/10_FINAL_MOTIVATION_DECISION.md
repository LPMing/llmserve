# Final motivation decision — shared NIC and cross-request communication

Date: 2026-10-12

## Decision codes

**`SERVING_IMPACT_BUT_NO_SCHEDULING_HEADROOM`** — the bounded integrated
FlowSim study observes policy-dependent Decode TBT, but does not establish
that a new request-/collective-aware method improves on static EP_FIRST.
EP_FIRST has no observed KV TTFT cost in this workload and removes nearly
all observed Decode-side damage from KV_FIRST.

**`NETWORK_CONTENTION_ONLY` for the tested KV–KV shard-tail cases**, plus
**`SERVING_IMPACT_BUT_NO_SCHEDULING_HEADROOM` for the bounded Decode cases**.
The overall decision is **`NO_MEANINGFUL_MOTIVATION` for a new fine-grained
scheduler in the tested envelope**: shared-resource contention is real in
FlowSim, and some class policies affect serving, but the event-derived
request-TTFT bound is zero for candidate KV and EP_FIRST captures the measured
cross-class Decode headroom. This is not evidence that other topologies or
traffic mixes never contend.

This is **not** a CCF-B/A paper go decision. The next permitted research
step, if the project continues, is a narrow packet-level mechanism validation
of the surviving class-level effect—not another scheduler formula. The strict attachment
labels `A_NETWORK_MOTIVATION_CONFIRMED` and
`B_SHARED_NIC_PRIORITY_MOTIVATION_CONFIRMED` are **not assigned**: A lacks
material serving-level gain, and B has no measured incremental headroom over
FAIR/static EP_FIRST. A paper claim requires a measured gap
that simple class priority and the closest prior methods do not close.

## Strongest result

In the controlled B workload (4 Prefill + 2 Decode physical servers, 8 GPUs
and 2×200G NICs/server, one ToR, two independent EP4 groups, 18 concurrent
model-derived P2D requests, 8 Decode seed requests):

- Each D0 RX rail has estimated average demand 182.396 Gbps against 200 Gbps.
  In the 74.321-ms candidate KV work window, measured time-weighted
  allocation is 87.29% on each rail (64.872 ms of active intervals); the
  largest busy episode is 1.522 ms. The 31.540-MiB peak is **analytical
  residual fluid backlog**. FAIR KV/EP simultaneous-active time is 1.296 ms
  (1.74% of that window).
- FAIR seed TPOT/mean ITL is 6.045367 ms; EP_FIRST is 6.008587 ms (-0.61%);
  KV_FIRST is 8.733146 ms (+44.46%).
- EP CCT p99 is 12.464 us for FAIR, 11.020 us for EP_FIRST, and 1,326.375 us
  for KV_FIRST. The large KV_FIRST tail is a FlowSim strict-class-fluid
  result, not a packet-level priority inversion measurement.
- Candidate request TTFT is unchanged by policy at 74.468 ms (2048 tokens)
  and 57.757 ms (1024 tokens). Candidate KV handoff spans change by only
  fractions of a microsecond among FAIR/EP_FIRST/KV_FIRST.
- EP_FIRST does not move the seed ITL p99 (8.164016 ms) versus FAIR, but it
  does avoid the KV_FIRST p99 tail (46.827701 ms).

The smaller A7L2M point has FAIR EP CCT p99 13.1% above the EP-isolated
virtual-capacity counterfactual, while the seed token ITL p99 is unchanged and
candidate TTFT is unchanged. This is a modest mechanism observation, not a
large serving-level optimization headroom.

## What is and is not proven

**Proven within this tested FlowSim configuration:**

- cross-request P2D/EP path and time overlap on a shared D0 NIC-facing
  directed resource;
- policy-dependent collective CCT and integrated seed token interval;
- layerwise KV handoff/TTFT remains nearly insensitive to those policy
  changes at this operating point;
- a simple EP_FIRST class rule is already a strong choice here.

**Not proven:**

- packet-level queueing, RDMA QP arbitration, ECN/CNP, PFC, DCQCN or switch
  priority effects;
- exact GateRouter-derived EP A2A (the tested path is AG/RS peer expansion);
- natural workload frequency or production SLO impact;
- request-specific or collective-specific priority benefit over EP_FIRST;
- a single uninterrupted saturation episode (measured demand is recurrent
  layerwise bursts, despite 87.29% time-weighted allocation);
- TTFT/TBT SLO attainment (no grounded thresholds were set);
- a CCF-B/A-level novel scheduling algorithm.

## Main weaknesses / reviewer risks

1. The most dramatic number compares KV_FIRST with EP_FIRST, while the
   deployable baseline FAIR is only 0.61% worse in mean seed token interval
   and identical in P99.
2. The high-load controlled phase and same-timestamp candidate burst are a
   mechanism fixture, not a production prevalence study.
3. FlowSim is fluid and does not model packet/RNIC/switch priority behavior.
4. The MoE collective realization is AG/RS rather than exact routed A2A.
5. Eight seed requests provide limited independent request-level replication;
   pooled token intervals are correlated.
6. Existing work overlaps substantially: Nuska for multi-stage P2D/KV/collective
   TTFT scheduling; STORM for NIC-level dependency-aware RDMA scheduling;
   FuseLink for multi-GPU/multi-NIC communication; coflow and pFabric for
   barrier grouping and flow priority.

## Recommended next action

Do not add another FlowSim priority formula. First export this exact bounded
event schedule and physical GPU/NIC mapping to a packet-level backend or
small testbed, retaining ACK/CNP traffic and legal queue semantics. Verify
the sign and scale of FAIR/KV_FIRST/EP_FIRST collective and TBT effects. If
that validates, the next research question must be sharpened around an
observed gap that EP_FIRST cannot solve (for example an actually observed
same-class Decode-barrier conflict)—not assumed in advance. If not, record a
negative result and stop the fine-grained-priority direction.

## GPU/runtime answer

The simulator event loop is CPU-side Python/FlowSim; the RTXPRO6000 label is
the hardware used to generate the input compute profile, not an accelerator
executing this simulation. Selecting a faster GPU profile would alter
simulated compute intervals and overlap, but would not shorten simulator wall
time. In the runs here, wall time was about 37–43 seconds per case, so a GPU
upgrade is not the relevant speed lever.

## Required questions, answered

1. **每台服务器两张 NIC 分别承担多少 KV/EP？** 在 B 的主要点上，每个 D0 接收方向的模型/profile 推导需求为 P2D KV 180.990 Gbps + EP 1.405 Gbps。实际 FlowSim P2D release-to-ready 窗口为 74.321 ms；两个 rail 各自时间加权分配率为 87.29%，而不是把双向或双 rail 合并统计。FAIR 下每 rail KV+EP 同时活跃 1.296 ms。
2. **需要多少 GPU/request/batch？** 本次构造的双 rail 高平均负载点使用 4 个 Prefill + 2 个 Decode 物理服务器（共 48 GPU；每台 8 GPU、2×200G NIC）。每条 D0 RX rail 上有 9 个并发 P2D producer requests（7×2048-token + 2×1024-token），另有一个 4-rank EP4 seed group；两条 rail 合计 18 个 P2D requests、8 个 Decode seed requests、2 个独立 EP4 batches。配置为每个 P2D request 分配独立 Prefill logical instance，producer ranks 分布在 4 台 Prefill server 的 32 GPU 内；Decode 有 8 个 EP participants。实测的是两条 D0 RX rail 各自 87.29% 的窗口时间加权占用，不是连续 87.29% 饱和，也不代表所有服务器的 TX/RX NIC 都处于该负载。该点是受控 workload，不代表生产到达率。
3. **RTX PRO 6000 profile 能否合法生成负载？** 能在模型/profile 驱动的 FlowSim 中达到每 rail 87.29% 时间加权带宽占用；P2D 每层 4 MiB（2048-token TP1 请求）或 2 MiB（1024-token TP1 请求），实际候选请求有完整 48 层。这里的 profile 只提供计算时序，不是 GPU 跑仿真。
4. **Direction A 何时影响 serving barrier？** 三类既有 cross-request case 都有网络侧证据，但 serving 暴露强度不同。KV–KV 的 128-token victim 在与 2048/8192-token 背景并发时，shard-FCT mean/P99 为 +10.91%/+25.35%，但 last-required-shard、KV-ready 和 TTFT 不变，说明单个 shard tail 被 request max-barrier slack 吸收。EP–EP 两个合法独立 EP4 group 共用 directed cut 时，dispatch CCT +6.39%、combine +1.58–3.11%，累积到 TPOT/TBT 为 +0.75–0.80%，TTFT 不变。KV–EP 最新 A7 点的 EP CCT P99 比 EP_ISOLATED 高 13.1%，但 seed ITL P99 与候选 TTFT 不变；更早的 corrected D4+KV 点为 +1.08% EP CCT P99、TPOT mean <0.01%。细节见 `02_DIRECTION_A_PRIOR_CASES.csv`；这些数据是不同版本/实验轮次的补充证据，不应混成单一矩阵。
5. **共享 NIC 是否产生普通 FAIR 无法保护的紧迫通信？** 拓扑确认 4 GPU ranks 共用一个 200G NIC rail，FlowSim 观察到实际共享。KV_FIRST 可严重拖慢 EP，但 FAIR 到 EP_FIRST 的 seed mean TPOT 改善只有 0.61%，ITL P99 不变。尚不能说 FAIR 已造成显著、不可接受的 urgency miss。
6. **紧迫度由什么决定？** 机制上由 Serving DAG 的 request/collective/token barrier 依赖决定，不是流量类别本身。实测 B 中 EP collective 位于当前 token barrier；18 个候选 P2D request 的全部 48 层 KV 流都在 Prefill 完成回调前结束，最后 KV completion 仍比 handoff 早约 0.654–0.800ms，因此这些请求在该点没有可转化为 TTFT 的 KV 网络紧迫度。没有运行 request-targeted priority replay，也没有测同类 flow 的 FCT 重分配效果。
7. **低紧迫流是否持续占用资源、紧迫流等待？** KV_FIRST 下，EP 活跃/排队时间与 KV 共存 62.625 ms（P2D 工作窗口的 84.26%），这是 FlowSim strict class allocation 造成的。FAIR 下仅 1.296 ms 重叠（1.74%），EP_FIRST 下 0.463 ms（0.62%）。只能说明该模型中的 class policy 服务差异，不能叫真实 RNIC/QP priority inversion。
8. **竞争属于哪一层？** 已验证的是 directed-link fluid bandwidth allocation + EP collective barrier + scheduler completion feedback。没有 software submission queue、RNIC QP scheduler、packet switch queue、ECN/PFC/DCQCN 或 packet HOL 证据。
9. **保持总容量/字节不变的最大理论收益？** A 的理想化完全暴露上界约 93 us/token，约为基线 5.876 ms TBT 的 1.58%；它是假设相关层差异完全串行暴露的网络估计，不是算法实测。B 的事件账本给出候选 KV 的 TTFT oracle 上界为 0：KV 都先于固定 Prefill-completion handoff 完成；EP_FIRST 已匹配 EP_ISOLATED，FAIR→EP_ISOLATED 的 mean TPOT 上界收益是 0.61%，ITL P99 是 0%。request-priority schedule replay 未运行，SLO 未定义。
10. **实际 TTFT/TBT/SLO 改善与副作用？** 候选请求 TTFT 对所有 policy 相同：长 prompt 74.468 ms、中 prompt 57.757 ms。8 个 24-token seed requests 的 mean TPOT：FAIR 6.045367 ms、EP_FIRST 6.008587 ms、KV_FIRST 8.733146 ms；ITL P99 分别 8.164016、8.164016、46.827701 ms。没有固定的真实 SLO threshold，故无 SLO attainment 结论。KV_FIRST 没有测到候选 TTFT 变差，但该小样本不代表普遍公平性。
11. **是否比固定优先级/SJF/EDF/LLF 有额外动机？** 没有证明。B 的 serving-level上界显示该固定 workload 无 request-targeted KV TTFT收益，EP_FIRST 已取得可见 cross-class收益；没有执行针对 shard FCT 的 request-priority replay。且已有 Nuska、STORM、FuseLink、coflow、PDQ/PIAS/QCLIMB 等覆盖大量泛化流级/依赖优先级思路。
12. **问题在 NIC 还是 fabric？** 观测的瓶颈资源是 FlowSim 拓扑中的 D0 NIC-facing 200G directed edge `60->56` / `60->57`。此抽象不能区分物理 RNIC内部仲裁、NIC线缆和ToR端口队列，也没有证据定位到 fabric spine（本拓扑无 spine）。因此只归因于“建模的 scale-out receiver rail”，不能更具体。
13. **为什么没有明显、可优化的 serving 收益？** Direction A 的机制并非完全不存在：KV–KV 单 shard P99 曾增加 25.35%，但它不是 request 最后完成 shard，handoff/TTFT 因而不变；EP–EP 的 CCT 延迟经 48 层传播后，TBT 增幅仍只有 0.75–0.80%；KV–EP A7 下 fairness 与隔离对照的 EP CCT P99 差 13.1%，但 ITL P99 不动。Direction B 每条目标 D0 RX rail 的估算平均需求约 182.396/200 Gbps，候选窗口时间加权 allocation 87.29%，但 busy 分成 207 个片段、最长约 1.522 ms，FAIR 下 KV/EP 同活跃时间仅 1.74%。综合原因是服务屏障的 max-completion/slack 隐藏了许多非末完成 shard 的延迟、EP 网络时间占 token 周期比例很低；在 B 的 class-policy 对照中 EP_FIRST 已近乎消除 EP 侧损害。FlowSim 不能说明真实 packet/NIC 队列调度。证据边界和历史数据来源分别记录在 `02_DIRECTION_A_PRIOR_CASES.csv` 与 `02_DIRECTION_A_GO_NO_GO.md`。
14. **哪个方向有尚未解决的论文动机？** 在当前合法 workload 和 FlowSim 资源模型内，没有方向达到新调度动机门槛。A 有 flow/shard 与 collective 竞争，但 request/token barrier 暴露小；B 显示网络类别排序能影响 Decode，但 FAIR→EP_FIRST mean 收益仅 0.61%、P99不变，且 event-ledger TTFT 上界为零。packet-level物理优先级仍未验证，因此不外推为真实NIC/交换机上的普遍否定结论。结论为 `SERVING_IMPACT_BUT_NO_SCHEDULING_HEADROOM` + `NO_MEANINGFUL_MOTIVATION`（限已测范围），不是 CCF-B/A GO。
