# RIQA-28: Expert shower multiplier of 0 is silently discarded — shower continues to consume full water volume

**Jira:** [RIQA-28](https://acfuture-inc.atlassian.net/browse/RIQA-28)
**Type:** Bug | **Status:** To Do | **Priority:** Medium
**Assignee:** Cooper | **Labels:** NewIssue
**Created:** 2026-05-16 | **Updated:** 2026-05-16

## Description

Steps to Reproduce:

1. Navigate to https://ac-future-water.elevatics.site/ (v0.3)
2. Set Expert=2, click Save & Compute, note the Shower daily_fresh_gal baseline
3. Find the Expert Shower Multiplier input (Section 3 / Behavior Multipliers)
4. Set Expert Shower Multiplier to 0
5. Click Save & Compute
6. Check /api/results Shower daily_fresh_gal

Expected Result:

A shower multiplier of 0 should result in 0 gal/day shower consumption (zero scale factor = no water used for showers).

Actual Result:

* With Expert Shower Multiplier = 0, Shower daily_fresh_gal remains 13.3 gal/day — identical to the default (multiplier=0.7) baseline.
* Confirmed via /api/inputs: expert_shower_mult returns undefined, meaning the value 0 is discarded rather than stored.
* The multiplier appears to be ignored when set to 0, treating the input as "not provided" rather than as the literal value zero.
* This prevents users from setting shower usage to zero and makes the zero value behave unexpectedly compared to other numeric inputs.
