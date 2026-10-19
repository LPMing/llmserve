# 03 — Natural workload exposure review

## Ex-ante selection and denominator discipline

This audit reused the previously frozen natural-window catalog rather than
selecting windows by observed slowdown. Its candidate inventory is
[`04_NATURAL_EXPOSURE_WINDOWS.md`](../experiments/pd_kv_ep/joint_exposure/reports/04_NATURAL_EXPOSURE_WINDOWS.md).
The three most relevant retained windows for the old KV/EP question are Azure
Code `013818`, Azure Conversation `06210`, and the BurstGPT `148333` candidate.
The old line has usable integrated/event joins for the two Azure prefixes. The
BurstGPT subset in this audit was only built as a bounded network-only A2A
screen; it has no serving scheduler result.

## What counts as exposure

- **Network busy/coactive:** KV and EP are active on the same directed link or
  route in a time interval.
- **Network critical:** a measured counterfactual shows that this overlap
  delays the request's last required KV shard or an EP round's last peer.
- **Serving exposed:** that delay survives Prefill compute slack, Decode
  capacity wait, or other compute overlap and changes a serving event.
- **Scheduling opportunity:** a legal same-workload service-order change
  improves a global metric beyond a strong baseline without material harm to
  other requests.

The data establish some coactivity, not the latter three levels.

## Natural windows

| Window | Requests/events | Observed same-link coactivity | Serving/barrier evidence | Decision |
|---|---|---|---|---|
| Azure Code `013818`, first 44 integrated requests | 22,464 EP collectives; 4,855 (21.61%) have critical-peer-route same-directed-link coactivity with KV. In the selected 463–466ms subwindow, 42/42 collective rows are coactive. | In broad 450–475ms, 182/331 coactive collectives have mean CCT 29.365µs vs 38.626µs for noncoactive; both P99 45.644µs. This unmatched association does not show contention-induced delay. | All 44/44 last KV handoffs precede Prefill completion; Prefill-minus-last-KV slack min/P50/P95 = 0.709/1.232/1.612ms. No isolated/matched counterfactual shows a critical barrier shift. | Natural sharing verified; serving exposure not demonstrated. |
| Azure Conversation `06210`, first 16 integrated requests | 73,632 EP collectives; 1,313 (1.783%) have critical peer-route same-directed-link coactivity. | Coactive descriptive mean/P99 15.883/44.333µs; no matched causal delta. | All 16/16 last-KV completions precede first Decode batch; slack min/P50/P95 = 0.709/1.175/1.517ms. Whole-prefix serving values are baseline, not gains. | Natural KV barrier hidden behind Prefill. |
| Azure Code `013818`, 1.5× interval compression diagnostic | Same first 44 requests/order/tokens; arrival intervals compressed, so this is not natural base load. | Coactivity fraction 16.96%→15.89%; EP CCT P95/P99 unchanged. | TTFT P99 +0.22%, TPOT P99 +1.95%, TBT P99 +5.05%; these are one diagnostic prefix and no full-interval link sidecar is retained. | Did not expose a new barrier; do not increase compression further. |
| BurstGPT `148333`, first 16 records (this audit's new-line screen) | Source arrivals are preserved: 16 requests, 2,203 input tokens, 715 output tokens; 14 tied at each of two source timestamps, span 1.0s. | The network-only builder places model-derived P2D/EP events on common topology; this is not an integrated natural-coactivity fraction. | No serving DAG, no lane-free join, no actual token-specific GateRouter logits. | Cannot count as old-line natural serving evidence. |

Every denominator is explicitly shown. The Azure ratios are **collective rows
with route coactivity / collective rows in that analyzed prefix**, not request
fractions, SLO miss rates, or causal impact rates. No exposure percentage is
reported where the necessary per-event join is absent.

## Old-line gate result

The old policy line does not satisfy its frozen Gate B: two natural windows do
not show a consistent positive request/token barrier effect. A 21.61% route
coactivity ratio is not 21.61% network exposure; all sampled KV handoffs retain
positive compute slack, and observed coactive EP means are not higher. The
network is occasionally busy, but measured natural evidence does not establish
that it is critical or scheduler-avoidable.

