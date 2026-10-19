# 10 — Theory / simulation discrepancy log

## This audit

No FlowSim, ns-3, or Serving performance experiment was run, so there is no
new theory-versus-performance discrepancy to report. This is intentional: the
model/profile/rank-map/DAG gates are not passed.

| Item | Prediction / expectation | Observation | Classification |
|---|---|---|---|
| P0 payload work under uniform random top-k | At higher EP, selected owner count grows much slower than `p−1`, so sparse payload work may be lower | Analytic expectation only; no Qwen route matrix and no execution timing | Assumption-limited, not a simulator discrepancy |
| Historical AE profile use | EP32/64 natural AE counts may be below 8 | 3,102,720/3,104,160 weighted retained queries are below minimum and clamp to AE=8 | Proven input-domain mismatch |
| Historical exact-P2P sidecar label | Could be read as exact learned routing | Sidecars say BALANCED; route origin is scheduled-token count; they are analytic policy artifacts | Proven provenance limitation |
| S16 rank placement | 128 physical GPUs should match model rank IDs | Config builder derives 192 ASTRA logical ranks while topology lists 128 GPU endpoints and no FlowSim rank map | Proven mapping inconsistency / unresolved semantics |
| Sparse A2A DAG | A converter helper exists | Standard trace emits AG/RS; graph generation does not pass route matrix/EP rank list | Proven not-integrated code path |

## Historical interpretation restriction

This report does not retroactively invalidate every retained network result.
It does prohibit treating the retained BALANCED sidecars as real learned Qwen
routing, using AE-clamped EP32/EP64 compute as calibrated Serving timing, or
assuming that the S16 generated logical ranks were mapped to the physical GPU
endpoints without a run-specific rank map.
