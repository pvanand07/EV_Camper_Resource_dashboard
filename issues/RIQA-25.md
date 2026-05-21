# RIQA-25: Plan tab: "Add X gal of tank capacity" recommendation uses wrong daily consumption figure, producing an incorrect capacity estimate

**Jira:** [RIQA-25](https://acfuture-inc.atlassian.net/browse/RIQA-25)
**Type:** Bug | **Status:** To Do | **Priority:** Medium
**Assignee:** Aishwarya Hoonur | **Labels:** NewIssue
**Created:** 2026-05-16 | **Updated:** 2026-05-16

## Description

Steps to Reproduce:

1. Navigate to https://ac-future-water.elevatics.site/
2. Set Expert count = 2, Fresh Capacity = 50 gal, Current Fresh = 50 gal
3. Set Target Autonomy Days = 10
4. Click Save & Compute, navigate to the Plan tab
5. Read the gap summary recommendation: "Cut X gal/day or add Y gal of fresh tank capacity"

Expected Result:

The recommended additional tank capacity should equal: (target_days - runway_days) × actual_daily_usage. With 26 gal/day and a 7.92-day deficit, the correct figure is 7.92 × 26 = 205.9 gal.

Actual Result:

* The recommendation states: "add 190 gal of fresh water tank capacity."
* However, the actual daily fresh consumption per /api/results is 26.0 gal/day, giving a required capacity of 7.92 × 26.0 = 205.9 gal — not 190.
* The discrepancy (190 vs 206 gal) suggests the calculation uses a different daily rate (approximately 24 gal/day) than what the activity engine reports (26 gal/day).
* A user following this recommendation would install \~16 gal less tank capacity than actually needed and would still run out of fresh water before their 10-day trip ends.
