# Directions D/E — theoretical exclusions

## D. Generic traffic-class, flow, or request priority

The historical controlled EP64 experiment already shows a fixed EP_FIRST policy can strongly improve EP CCT and TBT in its aligned case, while natural windows often do not expose the traffic delay. Other tests show large shard/FCT or queue deltas can be hidden by the last-required-flow barrier and serving slack. A request/deadline or stage-aware priority proposal also directly overlaps Nuska/MFS and classical EDF/LLF/coflow scheduling. Renaming such a priority as “joint” would not add a serving control variable or prove incremental headroom. No new D experiment was launched.

## E. Progressive Push / early KV release

The separate repository audit documents an opt-in logical Progressive Push implementation and its semantic requirements. The current task expressly says not to reimplement it. It is a transfer-protocol/architecture direction, not an untested replacement for A/B/C. No E performance comparison was run or imported into this mission's result table.

Both are exclusions from the current candidate set, not claims that every conceivable variant has been experimentally falsified.
