# RIQA-23: Climate Multiplier produces incorrect results — higher values reduce water consumption instead of increasing it

**Jira:** [RIQA-23](https://acfuture-inc.atlassian.net/browse/RIQA-23)
**Type:** Bug | **Status:** To Do | **Priority:** Medium
**Assignee:** Cooper | **Labels:** NewIssue
**Created:** 2026-05-16 | **Updated:** 2026-05-16

## Description

Steps to Reproduce:

1. Navigate to https://ac-future-water.elevatics.site/
2. Set Expert count = 2, Fresh Capacity = 100 gal, Current Fresh = 80 gal, all defaults
3. Click Save & Compute and note the total fresh water usage (baseline)
4. Change Climate Multiplier to 2 and click Save & Compute — compare total fresh usage
5. Change Climate Multiplier to 10 and click Save & Compute — compare total fresh usage

Expected Result:

Climate Multiplier should scale water consumption proportionally. At 2×, daily fresh usage should double. At 10×, it should increase tenfold.

Actual Result:

* Climate=1 (baseline): 26.0 gal/day total fresh consumption.
* Climate=2: still 26.0 gal/day — no change (0% increase, expected +100%).
* Climate=10: 6.0 gal/day — LOWER than baseline, consuming less water at a higher multiplier (−77%, expected +900%).
* The multiplier appears to have no effect at values near 1, and produces an inverted/incorrect result at high values.
* Note: RIQA-7 reported "no effect" — this test reveals the additional finding that extreme values produce counter-intuitive negative scaling, making the bug more severe than originally documented.
