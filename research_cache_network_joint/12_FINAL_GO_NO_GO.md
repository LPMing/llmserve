# Final GO / NO-GO: Cache-Conditioned Network–Serving Optimization

Date: 2026-10-14.  
Overall status: **`NO_VALID_PAPER_MAINLINE` for the proposed >15% cache-conditioned joint optimization claim in the tested configuration.**

## Gate outcomes

| Gate | Outcome | Evidence |
|---|---|---|
| Destination prefix reuse protocol | Mechanism correctness **PASS** in simulator | Full, partial, miss, reservation, concurrent refs, capacity/eviction fallback tests pass; bytes are conserved |
| A: ≥15% client-visible TTFT | **`A_15_PERCENT_TTFT_FAIL` / not demonstrated** | Historical 16.8149% was based on P2D-ready as TTFT. A0/A2 sampler-ready proxy is identical at 27.068 ms; external client first-token event is not modeled |
| A: payload reduction | **PASS as a mechanism** | 403,537,920 B → 884,736 B per target, 99.7808% fewer P2D bytes under a verified 4096-token destination hit |
| B: ≥15% complete-session E2E | **`B_15_PERCENT_E2E_FAIL`** | 3P2D mean session finish improves 4.56%; slowest session worsens 7.26%; 4P1D DELTA mean improves 2.59% |
| DELTA increment on 3P2D | **No measured serving increment** | B2 session/token timestamps equal B1 despite lower P2D payload |
| Cache-only/static baseline sufficiency | No 15% solution established | Best tested static 3P2D is a modest mean improvement, not uniformly beneficial; DELTA changes no B-session timestamps |
| Network feedback incremental value | **Not established; Gate D not entered** | No qualifying serving-side incremental gain to attribute to network signal |
| ns-3 packet validation | **NOT_RUN** | No serving-level pass; FlowSim output is not packet queue/ECN evidence |
| Natural-workload support | **NOT_RUN / synthetic-only** | Controlled identical-prefix sessions only |

## Direct answers

1. **Can the quoted 16.81% TTFT upper bound be realized?** No. The calculation used an invalid event as TTFT. The sampler-ready proxy has no A0→A2 improvement; true client TTFT needs a distinct asynchronous token-delivery event in the simulator/runtime.
2. **What is the measured real control overhead for early destination lookup?** Unknown. The lookup and reserve/commit calls add zero simulated time. Local interpreter wall timing is not a distributed RPC or lease cost.
3. **Can repeated KV be safely omitted?** Yes, in the simulator protocol: a matching destination prefix is reserved and adopted, only missing suffix KV is sent, and miss/eviction/reservation failure falls back safely. Focused tests pass.
4. **Does the ideal 22.08% child E2E estimate survive full sessions?** No. Full-session 3P2D improves the mean 4.56%, while the slowest session regresses 7.26%. The child-only mean is not a substitute for full sessions.
5. **Does 3P2D preserve fixed active GPU/NIC resources?** It preserves five TP2 instances/ten active ranks, five server slots, and modeled 200-Gbps rail capacities. It does not model eight GPU senders contending per server NIC; 2P3D routing is unsupported.
6. **Was the result hidden by cache miss or Decode batching?** A0→A2 did realize the prefix hit and reduce bytes; the sampler-ready event did not move. In 3P2D, DELTA changes no session/token timestamps. Warm-up release, cache locality, and batching are included in the actual full-session result.
7. **Has static P:D solved the problem?** It is the best measured mean full-session configuration here, but only +4.56% and with a 7.26% maximum-session regression. It does not meet the predeclared 15% criterion or prove universal sufficiency.
8. **Do network signals provide additional decision value?** Not demonstrated. Gate C/D were not run because there is no >15% candidate outcome and B2 has zero serving-time gain over B1.
9. **Is there ≥15% headroom over the strongest measured single-side baseline?** No demonstrated evidence. Best static mean improves 4.56%; A2 gives 2.59% mean session reduction in 4P1D; DELTA adds 0% measured latency on B1.
10. **Should this enter CCF-C/B algorithm design?** No, not on this evidence. Destination reuse is a valid mechanism result, but caching and static resource reconfiguration are known classes of mechanisms and this study has not shown a novel network/Serving joint increment.

## Final classification

```text
A_15_PERCENT_TTFT_FAIL
B_15_PERCENT_E2E_FAIL
DESTINATION_PREFIX_REUSE_PROTOCOL_PASS
SYNTHETIC_ONLY_RESULT
NETWORK_FEEDBACK_INCREMENTAL_VALUE_NOT_ESTABLISHED
NO_VALID_PAPER_MAINLINE
```

This is scoped to the audited simulator, fixture, model profile, and operating points. It is not a claim that destination KV reuse or cache-conditioned P:D changes can never help in a real deployment. It is a conclusion that the required >15% serving-level and incremental network-control evidence is absent here. Further work should first add an explicit client token-emission event and a measured control-plane protocol cost; it should not proceed to network-aware policy design based on the invalid historical TTFT field.
