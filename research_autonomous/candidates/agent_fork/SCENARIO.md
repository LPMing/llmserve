# Candidate: irregular agent fork-group KV placement

## Real workload and dependency definition

The pinned [FreeInference agentic trace](https://huggingface.co/datasets/harvardMadsys/freeinference_agentic_trace)
contains nested child sessions under a parent request's `tool_calls[].subagent`.
The extractor records two distinct group definitions:

1. **Same-request siblings:** at least two nested children attached to one
   parent LLM request. This is a ground-truth parent relationship.
2. **Cross-request overlap component:** children attached to any requests in
   the same parent session whose recorded session intervals overlap. This
   captures asynchronous fan-out, but the trace does not prove a common join
   dependency. It is reported separately.

For each group, sibling first-request block IDs yield a 16-token-granularity
common-prefix lower bound in the trace's `o200k_base` tokenizer. Those counts
cannot be converted exactly to a Qwen KV allocation without retokenizing the
unreleased prompt text. Session start/end times establish overlap and
release skew. The next parent request after the child interval is only a
*candidate* resume event; a negative or very large lag means the trace does
not establish a join. No parent JCT improvement is inferred from it.

## Measured evidence status

The full 16-week release contains 12,002 root sessions and 1,222,199 requests
when nested child sessions are counted recursively. There are 288 same-request
sibling groups, 280 with overlapping child-session intervals, 277 with both
overlap and at least 256 shared `o200k_base` tokens. The median width is 3,
the median first-request shared prefix is at least 7,864 `o200k_base` tokens,
and the median group span is 349.004 seconds. These groups occur in 191 root
sessions; they are uncommon at full-fleet scale. A further 43 overlapping
components join children spawned by different requests in the same parent
session; the trace does not prove these have one join target.

Only two same-request groups have every first-child provider prompt at most
2,048 tokens. For 219 groups that maximum is at most 16,384 provider tokens,
the largest context length in the available attention profile. This is a
rough length screen only: provider token counts and the trace's `o200k_base`
blocks do not match Qwen tokenization, later child requests may exceed the
profiled context, and none of the recorded provider models is the exact
profiled Qwen3 model. Of 263 groups with a later parent request, 76 have a
negative apparent join lag. A later request therefore does not establish a
join for the others either.

## Causal mechanism and metric

If one Prefill-produced shared prefix is needed by sibling branches placed
on several Decodes, each *distinct remote destination* may need a KV copy.
MoE expert placement is a separate intra-Decode concern and does not by
itself imply one full KV copy per expert GPU. A branching placement trades
the number of shared-prefix transfers against Decode queue/batch parallelism.
The metric for a genuine join is parent resume time; where a join is not
observed, report only child TTFT and completion distributions without a
program-level claim.

The trace records GLM/Minimax/DeepSeek and other provider calls rather than
the checked-in Qwen/Llama profiled models. The simulator has no measured
long-context profile for those providers, no full client egress event and no
fork-group DAG scheduling primitive. These are fidelity gates, not reasons to
manufacture a short-prompt or synchronous group.

`../../theory/agent_fork_screen/` maps the Qwen3 BF16 KV shape onto each
observed shared-prefix token count and charges all `width-1` extra copies to
one 200-Gbps source cut. The median copy budget is 52.16 ms. Its ratio to the
*different providers' observed* group spans is 0.016% at p50 and 0.77% at
maximum. Against each group's fastest child's provider TTFT, 54/288 ratios
exceed 10%; only eleven also have first-child provider prompts <=16,384,
overlapping intervals and <=1 s release skew. None uses the exact profiled
model. Some ratios exceed 100%, making the cross-tokenizer/cross-model
incompatibility visible. These values are screening flags, not bounds on a
Qwen run or end-to-end simulation results.
