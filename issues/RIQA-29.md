# RIQA-29: Greywater recycling reduces fresh water consumption even when grey tank capacity is set to zero

**Jira:** [RIQA-29](https://acfuture-inc.atlassian.net/browse/RIQA-29)
**Type:** Bug | **Status:** To Do | **Priority:** Medium
**Assignee:** Aishwarya Hoonur | **Labels:** NewIssue
**Created:** 2026-05-16 | **Updated:** 2026-05-16

## Description

Steps to Reproduce:

1. Navigate to https://ac-future-water.elevatics.site/ (v0.3)
2. Set Expert=2, all defaults, click Save & Compute — note total fresh consumption (baseline)
3. Set Grey Tank Capacity = 0 gal, Current Grey Level = 0 gal
4. Enable the Greywater Recycling toggle
5. Click Save & Compute — compare total fresh consumption to baseline

Expected Result:

With grey tank capacity = 0 gal, there is no storage medium for grey water. Recycling should be automatically disabled or have no effect. Total fresh consumption should remain at baseline.

Actual Result:

* With grey cap=0 and recycling ON, total fresh consumption drops from 24.0 gal/day to 20.4 gal/day — a reduction of 3.6 gal/day despite zero grey tank capacity.
* The system recycles water from a tank that cannot hold any water.
* The grey tank projection shows daily_delta = 15.1 gal being produced and routed to a 0-capacity tank (days_remaining = 0, status = Dump Soon!).
* No warning or error is shown about the logical impossibility of recycling from a zero-capacity tank.
