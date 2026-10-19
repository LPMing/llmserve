"""Tiny independent integer-time reference scheduler for MoE owner DAGs.

This is an analytical validation tool only. It does not call FlowSim, serving,
ASTRA-Sim, or any project scheduling/allocation code. Durations are abstract
integer ticks and must not be interpreted as Qwen3 measurements.
"""

from functools import lru_cache
from itertools import product


def solve(dispatch, compute, combine):
    """Return (exact_streaming_makespan, lower_bound, bulk_makespan).

    Model: one unit-capacity forward link shared by all dispatch transfers,
    one independent full-duplex reverse link shared by all combines, and one
    exclusive compute resource per owner. Transfers are preemptible at integer
    tick boundaries; owner compute starts as soon as its dispatch finishes.
    A combine is released after that owner's compute. There is no latency,
    launch, or buffer cost. This deliberately idealized model only checks the
    DAG equations and the exhaustive solver; it is not a hardware calibration.
    """
    dispatch = tuple(map(int, dispatch))
    compute = tuple(map(int, compute))
    combine = tuple(map(int, combine))
    n = len(dispatch)
    if not n or len(compute) != n or len(combine) != n:
        raise ValueError("dispatch, compute, combine must have equal nonzero length")
    if min(dispatch + compute + combine) < 0:
        raise ValueError("durations must be nonnegative")

    # c_rem=-1 means owner compute is waiting for its dispatch; 0 means done.
    start = (dispatch, (-1,) * n, combine)

    def normalize(state):
        d, c, r = state
        c = tuple(compute[i] if d[i] == 0 and c[i] == -1 else c[i]
                  for i in range(n))
        return d, c, r

    @lru_cache(None)
    def remaining_time(raw_state):
        d, c, r = normalize(raw_state)
        if all(x == 0 for x in d + c + r):
            return 0

        d_choices = [i for i, value in enumerate(d) if value > 0]
        r_choices = [i for i, value in enumerate(r)
                     if value > 0 and c[i] == 0]
        # Work-conserving service is without loss for this preemptive,
        # zero-setup model. The two directed links may serve simultaneously.
        if not d_choices:
            d_choices = [None]
        if not r_choices:
            r_choices = [None]

        best = None
        for di, ri in product(d_choices, r_choices):
            nd, nc, nr = list(d), list(c), list(r)
            if di is not None:
                nd[di] -= 1
            if ri is not None:
                nr[ri] -= 1
            for i in range(n):
                if nc[i] > 0:
                    nc[i] -= 1
            next_state = normalize((tuple(nd), tuple(nc), tuple(nr)))
            candidate = 1 + remaining_time(next_state)
            best = candidate if best is None else min(best, candidate)
        return best

    exact = remaining_time(start)
    chain = max((dispatch[i] + compute[i] + combine[i]
                 for i in range(n)), default=0)
    resource_lb = max(sum(dispatch), sum(combine), max(compute, default=0))
    lower = max(chain, resource_lb)
    bulk = sum(dispatch) + max(compute, default=0) + sum(combine)
    if not lower <= exact <= bulk:
        raise AssertionError((dispatch, compute, combine, lower, exact, bulk))
    return exact, lower, bulk


def main():
    cases = {
        # Different owners dominate dispatch, compute, and return: a positive
        # ideal overlap witness, not a model-derived workload.
        "cross_owner_positive_toy": ((6, 2), (1, 6), (2, 5)),
        # One owner dominates the workload; the second owner contributes only
        # a small tail, so cross-owner overlap has little theoretical value.
        "single_owner_dominant_negative_toy": ((8, 1), (6, 1), (4, 1)),
        # Symmetric owners: no owner-ordering opportunity in this model.
        "symmetric_negative_toy": ((3, 3), (4, 4), (2, 2)),
    }
    print("case,dispatch_ticks,compute_ticks,combine_ticks,lower_bound,exact_streaming,bulk,ideal_gap")
    for name, (d, c, r) in cases.items():
        exact, lower, bulk = solve(d, c, r)
        print("%s,%s,%s,%s,%d,%d,%d,%d" % (
            name, ";".join(map(str, d)), ";".join(map(str, c)),
            ";".join(map(str, r)), lower, exact, bulk, bulk - exact))


if __name__ == "__main__":
    main()
