# RIQA-17: Input Validation: Negative activity flow rate (gal/min) accepted in Section 4, producing corrupted water consumption values

**Jira:** [RIQA-17](https://acfuture-inc.atlassian.net/browse/RIQA-17)
**Type:** Bug | **Status:** To Do | **Priority:** Medium
**Assignee:** Aishwarya Hoonur | **Labels:** NewIssue
**Created:** 2026-05-16 | **Updated:** 2026-05-16

## Description

Steps to Reproduce:

1. Navigate to https://ac-future-water.elevatics.site/
2. Set Expert count = 2, Fresh Capacity = 100 gal, Current Fresh = 80 gal
3. Scroll to Section 4 — Activity Engine
4. Set the Shower Flow (gal/min) field to -3
5. Click Save & Compute

Expected Result:

Flow rate must be a positive value. A negative flow rate is physically meaningless (water cannot flow backwards). The field should reject the input or show a validation error.

Actual Result:

* The negative flow rate is accepted and saved to the server (confirmed: GET /api/inputs shows flow_gal_per_min = -3).
* Shower daily consumption drops from the correct 21.0 gal/day to -4.2 gal/day — negative water usage.
* The Plan tab and Realtime tab compute using this corrupted value. Fresh tank projections become meaningless.
* This is a distinct input class from the occupant count and behavior multiplier validation already filed (RIQA-8, RIQA-9) — Section 4 activity parameters have no server-side minimum enforcement.
