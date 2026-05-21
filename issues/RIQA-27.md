# RIQA-27: Input Validation: Toilet events per day accepts negative values, producing negative black tank and fresh water consumption

**Jira:** [RIQA-27](https://acfuture-inc.atlassian.net/browse/RIQA-27)
**Type:** Bug | **Status:** To Do | **Priority:** Medium
**Assignee:** Aishwarya Hoonur | **Labels:** NewIssue
**Created:** 2026-05-16 | **Updated:** 2026-05-16

## Description

Steps to Reproduce:

1. Navigate to https://ac-future-water.elevatics.site/ (v0.3)
2. Set Expert=2, default tank values, click Save & Compute to establish baseline
3. Scroll to Section 4 — Activity Engine, find the Toilet row
4. Set Toilet Events/Day to -5
5. Click Save & Compute
6. Inspect /api/results for the Toilet activity

Expected Result:

Negative events per day is physically impossible and should be rejected with an inline validation error. The field should only accept zero or positive integers.

Actual Result:

* Value -5 accepted and stored server-side (confirmed via /api/inputs: events_per_day_per_person = -5).
* api/results: Toilet daily_fresh_gal = -6.0 gal/day and black_added_gal = -6.0 gal/day (2 persons × 0.6 gal/unit × (-5) = -6).
* Negative toilet events implies the toilet is removing sewage from the black tank and producing fresh water — physically impossible.
* fresh_attrib_pct = -41.67%, corrupting the entire activity attribution breakdown in the Results table.
