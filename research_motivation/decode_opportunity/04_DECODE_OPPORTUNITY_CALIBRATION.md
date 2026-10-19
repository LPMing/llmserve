# 04 — Decode-opportunity calibration

Status: `CALIBRATED_WITH_NATURAL_EVENTS`; the event ordering is real within this simulator configuration, but the calibration is narrow and controlled.

## Configuration and procedure

Two independent Decode instances each use TP2/EP2 and `max_num_seqs=1`. The target request pairing is fixed: request 3→D0 (instance 2), request 2→D1 (instance 3). Before adding the two target requests, the seed-only workload was run through the ordinary integrated scheduler. No scheduler decision timestamp was directly inserted or overridden.

The two seed prompts are both 128 tokens. D0's seed output is 12 tokens in the primary case; D1's seed output is 64 tokens. Both lanes start their first Decode batch at 24.692817 ms and complete it at 29.319441 ms. Their later token iterations are profile-backed. The seed-only result gives these lane-release events:

| Decode lane | Seed request | Output tokens | P2D-ready / first Decode batch | Slot becomes available |
|---|---:|---:|---:|---:|
| D0 / instance 2 | 1 | 12 | 24.692817 ms | 75.585681 ms |
| D1 / instance 3 | 0 | 64 | 24.692817 ms | 315.531153 ms |

The D0 seed's 11 measured inter-token intervals average about 4.63 ms; the D1 seed continues to occupy its one sequence slot while the two targets arrive. The two targets have identical arrival time, input length (2048), output length (2), and model-derived KV bytes. Their common P2D first-release boundary is 70.877817 ms. Thus the experiment does not phase-scan the target arrivals: the difference arises from the naturally simulated seed workload and the two independent schedulers.

## Opportunity condition

For target request 3 on D0:

- Selected-request offline control: P2D-ready 74.927908 ms, before D0 frees at 75.585681 ms; Decode capacity wait is 0.657773 ms and its first Decode batch starts at 75.585681 ms.
- FAIR: P2D-ready 78.966384 ms, after D0 frees; first Decode batch starts immediately at 78.966384 ms.

Therefore the request is eligible in time for the earlier D0 slot only in the selected-request control. Both runs record Decode batch id 11. The network policy changes the start time of that next batch; **it does not change the batch id or membership**. Request 2 is paired with D1, which remains occupied until about 315.53 ms, so completing it earlier does not expose an earlier Decode slot.

## Neighbor check and boundary

We changed only D0 seed output length by one token on either side of the primary 12-token calibration, keeping the targets, model, topology and policy pair fixed.

| D0 seed output | D0 slot release | Request 3 FAIR ready → second token | Request 3 opportunity-control ready → second token | Interpretation |
|---:|---:|---:|---:|---|
| 11 | 70.959057 ms | 78.954088 → 83.664588 ms | 74.916900 → 79.627236 ms | The earlier KV handoff is ready shortly after the lane frees; second-token-from-arrival improves 4.037352 ms. |
| 12 | 75.585681 ms | 78.966384 → 83.676884 ms | 74.927908 → 80.296017 ms | Handoff crosses the slot boundary; opportunity control starts the batch at slot release. |
| 13 | 80.255661 ms (FAIR run) | 78.975780 → 84.965997 ms | 74.927908 → 84.922641 ms | Both policies wait for the busy lane; only a 43.356 μs second-token difference remains. |

The 13-token pair has a small event-time drift between independently completed runs (the two slot-release timestamps differ by about 43 μs), so the 43.356 μs residual is not a robust effect estimate. The meaningful observation is the boundary: once the Decode slot remains busy beyond both P2D-ready times, the earlier network completion is almost entirely hidden by Decode capacity wait.

## Gate decision

`DECODE_OPPORTUNITY_EFFECT_CONFIRMED` is justified only as a controlled mechanism observation: an actual P2D-ready event can move relative to a naturally generated Decode slot and alter the modeled second-token/request-completion event. The effect is not robust across the adjacent 13-token condition, does not change batch membership, and is not yet a production workload claim. Do not proceed from this calibration directly to an online scheduler.
