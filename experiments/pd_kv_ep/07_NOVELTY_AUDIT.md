# Preliminary novelty audit

This is a focused overlap audit, not a complete literature review or a priority claim.

## Closest prior work

- Nuska, titled “Stage-Aware Communication Scheduling for Disaggregated LLM Serving” in the current arXiv listing, explicitly handles dependent multi-stage flows such as KV retrieval, collective communication and P2D transfer, and approximates least-laxity-first through stage-aware promotion. That is direct overlap with flow slack, stage dependencies and network-side urgency. See [arXiv:2603.17456](https://arxiv.org/abs/2603.17456).
- MFS is the earlier title/name used for the same work in project materials; do not count MFS and Nuska as two independent prior works. The current arXiv abstract reports stage-aware multi-stage flow scheduling and improved TTFT SLO attainment.
- Libra (NSDI 2026) uses flexible micro-request partitioning, a global scheduler selecting split points, local SLO-aware batch scheduling, and chunked KV transfer. This overlaps system-side request/compute partitioning coupled to KV movement. See [USENIX NSDI 2026 Libra](https://www.usenix.org/conference/nsdi26/presentation/ruan-libra).
- Preble (ICLR 2025) jointly schedules distributed prompts to co-optimize KV reuse and computation load balancing. This overlaps system scheduling of KV-dependent work, although not the proposed network-service exposure control. See [ICLR 2025 Preble](https://proceedings.iclr.cc/paper_files/paper/2025/hash/5bc342f48de8264779952fac378f96dc-Abstract-Conference.html).
- Coflow scheduling is an older but essential baseline family: application-stage completion depends on all member flows; classic work already optimizes communication-stage completion and uses coflow-level service semantics. See [Efficient Coflow Scheduling Without Prior Knowledge](https://doi.org/10.1145/2785956.2787480).

## Novelty boundary

Not novel by itself:
- prioritize flows by laxity/slack;
- protect stage-critical flows;
- schedule a coflow using its last completion;
- combine a request scheduler with an ordinary priority network scheduler;
- chunk or progressively transfer KV;
- use a serving DAG to derive flow deadlines without a distinct systems contribution.

Potentially distinguishable, but unproven:
1. System scheduling changes the exposure itself by changing batch/admission/phase/release geometry; network scheduling changes service time after release.
2. The optimization target is an end-to-end barrier exposure deficit across both P2D request barriers and recurrent MoE EP/Decode iteration barriers, rather than a single TTFT multi-stage flow chain.
3. The result demonstrates non-separable synergy: baseline, network-only, system-only and joint are evaluated on identical natural requests/bytes; joint improves serving while neither layer alone does.
4. The runtime receives barrier-aware signals at the communication layer without requiring clairvoyant future request knowledge, and the system-side action remains deployable.

None of points 1–4 has a complete positive experimental proof in retained artifacts. A paper pitch that currently says “dynamic exposure-aware scheduling” risks being read as a rebranding of least-laxity/stage-aware flow scheduling. A stronger novelty claim would require the matched four-cell experiment, measured exposure-window frequency, and an operational design that MFS/Nuska cannot emulate with a changed flow priority.

## Assessment

Novelty status: OPEN / HIGH RISK, not passed. The best next literature review should inspect the full Nuska/MFS algorithm and evaluation, then search recent work on network-informed batch admission, iteration-boundary scheduling, and system/network co-scheduling in disaggregated MoE serving. Do not claim “first” from this preliminary audit.

