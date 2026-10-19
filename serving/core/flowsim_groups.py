"""Small helpers for assembling rank-group FlowSim graph commands."""


def queued_group_graph_owners(member_ranges, workload_path, current_rank,
                              queued_workloads):
    """Resolve which rank queues owe each member's graph for one group round.

    A DP member's graph can be opened by any of its TP ranks. Therefore its
    ready workload is not necessarily queued under the instance's first rank.
    The current rank may own its graph directly; every other member must have
    a matching FIFO head on one of its local ranks.

    Returns ``(owners_to_pop, blockers)``. A nonempty blocker list means the
    group must not be submitted yet.
    """
    owners = []
    blockers = []
    current_rank = int(current_rank)
    for start, count in member_ranges:
        local_ranks = tuple(range(int(start), int(start) + int(count)))
        local_heads = [
            (rank, queued_workloads[rank][0])
            for rank in local_ranks
            if queued_workloads.get(rank)
        ]
        mismatches = [(rank, head) for rank, head in local_heads
                      if head != workload_path]
        if mismatches:
            blockers.extend((rank, "queued", head)
                            for rank, head in mismatches)
            continue
        matching = [rank for rank, head in local_heads
                    if head == workload_path]
        if matching:
            owners.extend(matching)
        elif current_rank not in local_ranks:
            blockers.append((int(start), "missing", None))
    return sorted(set(owners)), blockers


def instance_group_command(workload_path, ranks):
    """Build one FlowSim job containing every rank ET for an instance step.

    ASTRA's graph files are rank-local, but a TP/EP collective is not.  Sending
    each ET as an independent ``run`` command makes the FlowSim worker observe
    a one-rank communicator and incorrectly retire its collective nodes without
    network flows.  A group command keeps the instance's rank-local DAGs in one
    job so collective participants and their barrier are visible together.
    """
    members = sorted({int(rank) for rank in ranks})
    if not members:
        raise ValueError("an instance graph group must contain at least one rank")
    return "group %s %s" % (
        workload_path, ",".join(str(rank) for rank in members))
