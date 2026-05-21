# RIQA-21: Input Validation: Drinking activity gal/unit accepts negative values, producing negative fresh water consumption

**Jira:** [RIQA-21](https://acfuture-inc.atlassian.net/browse/RIQA-21)
**Type:** Bug | **Status:** To Do | **Priority:** Medium
**Assignee:** Aishwarya Hoonur | **Labels:** NewIssue
**Created:** 2026-05-16 | **Updated:** 2026-05-16

## Description

Steps to Reproduce:

1. Navigate to https://ac-future-water.elevatics.site/
2. Set Expert count = 2, Fresh Capacity = 100 gal, Current Fresh = 80 gal
3. Scroll to Section 4 — Activity Engine
4. Find the Drinking (Adults) row and set the Gal/Unit field to -1
5. Click Save & Compute
6. Check the /api/results response for Drinking (Adults) daily_fresh_gal

Expected Result:

The Gal/Unit field for drinking activities should only accept positive values. A negative water consumption for drinking is physically impossible.

Actual Result:

* The value -1 is accepted and stored on the server (GET /api/inputs confirms gal_per_unit = -1).
* API /api/results returns: Drinking (Adults) daily_fresh_gal = -2.0 gal/day (with 2 experts, -1 gal/unit × 2 persons = -2).
* The fresh_attrib_pct is also negative (-8.33%), corrupting the activity attribution breakdown.
* This is distinct from RIQA-9 (behavior multipliers) and RIQA-17 (flow rate) — it is the gal/unit field for discrete-consumption activities in Section 4.
