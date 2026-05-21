# RIQA-12: Realtime tab: Behavioral Drift at maximum produces identical day values on every Refresh (randomness is frozen)

**Jira:** [RIQA-12](https://acfuture-inc.atlassian.net/browse/RIQA-12)
**Type:** Bug | **Status:** To Do | **Priority:** Medium
**Assignee:** Cooper | **Labels:** NewIssue
**Created:** 2026-05-16 | **Updated:** 2026-05-16

## Description

Steps to Reproduce:

1. Navigate to https://ac-future-water.elevatics.site/
2. Set Expert count = 1, Fresh Capacity = 100 gal, Current Fresh = 80 gal
3. Drag the Behavioral Drift slider to 100% (maximum = 1.0)
4. Click Save & Compute, navigate to the Realtime tab
5. Note the per-day fresh usage values
6. Click "Refresh Realtime" several times and compare values each time

Expected Result:

With drift_seed = null (no fixed seed), each Refresh Realtime call should produce new random samples from the drift distribution N(1.0, sigma=0.5), resulting in different daily values on each refresh.

Actual Result:

* Day values are identical on every Refresh Realtime press. Observed on two consecutive runs: Day 1 = 10.37 gal, Day 2 = 16.97 gal, Day 3 = 10.63 gal — unchanged.
* API /api/inputs confirms drift = 1 and drift_seed = null, but the server returns the same samples regardless.
* The random seed appears to be cached server-side and never regenerated between /api/realtime calls.
* The Behavioral Drift feature cannot model day-to-day variability as described — it is functionally a fixed multiplier, not a stochastic model.
