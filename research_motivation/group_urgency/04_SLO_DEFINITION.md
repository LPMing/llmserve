# Token SLO definition and freeze status

## Result

No externally grounded TBT/ITL SLO or service contract was supplied for the Qwen3 / RTX PRO 6000 / batch-64 Decode fixture. No SLO threshold was selected after seeing a contention result, and no SLO attainment number is reported.

The task's 1%, 3%, and 5% relative headroom levels are used only as fixed **theoretical scale references**, not as SLOs. For the group64/context2048 profile-derived token interval estimate of 16.899 ms they correspond to 169.0, 507.0, and 845.0 µs. The identical-size, perfectly aligned all-phases ideal ceiling is 519.0 µs (3.07%); the largest heterogeneous A/B profile screen is only 53.4 µs (0.316%).

## Why no absolute threshold is frozen

- An 8-ms example target would already be below the profile-derived isolated interval of the tested 32–64 request/group points, so it cannot distinguish a network-induced miss from an infeasible baseline.
- Choosing a common absolute threshold within tens of microseconds of a predicted baseline could flip one deterministic deadline in a constructed fixture. With no external contract, that is a threshold selected to match the bound, not evidence of a production SLO problem.
- A relative threshold tied independently to each group's own isolated TBT would give the homogeneous groups equal normalized urgency; it would not test the proposed class-blind group differentiation.

The 1/3/5% figures and no-SLO decision were frozen before any new simulation; G2/G3 were gated off. Existing request/ITL timestamps remain raw latency evidence only.
