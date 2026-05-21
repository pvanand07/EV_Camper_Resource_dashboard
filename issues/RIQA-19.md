# RIQA-19: Plan tab: Activity reduction recommendation displays attribution percentage greater than 100% (e.g. "Kitchen Sink is 115% of the load")

**Jira:** [RIQA-19](https://acfuture-inc.atlassian.net/browse/RIQA-19)
**Type:** Bug | **Status:** To Do | **Priority:** Medium
**Assignee:** Aishwarya Hoonur | **Labels:** NewIssue
**Created:** 2026-05-16 | **Updated:** 2026-05-16

## Description

Steps to Reproduce:

1. Navigate to https://ac-future-water.elevatics.site/
2. Set Expert count = 2
3. Set Fresh Capacity = 50 gal, Grey Capacity = 50 gal, Black Capacity = 30 gal
4. Set Current Fresh = 50 gal, Current Grey = 30 gal
5. Enable Greywater Recycling toggle
6. Set Target Autonomy Days = 10
7. Click Save & Compute, navigate to the Plan tab
8. Read the activity reduction recommendations under Timeline Check

Expected Result:

Activity attribution percentages should sum to 100% across all activities. No individual activity can logically be more than 100% of the total load.

Actual Result:

* The Plan tab displays recommendation text such as: "Kitchen Sink is 115% of the load. Cut 60% -> -3.8 gal/day, +7.99 days."
* This occurs because greywater recycling reduces fresh consumption toward zero or negative, causing the fresh_attrib_pct calculation to overflow — individual activity percentages are computed relative to a near-zero or negative total.
* A percentage above 100% is displayed verbatim in the recommendation text shown to users, which is confusing and incorrect.
* The underlying API returns the inflated percentage values, and the frontend renders them without clamping or validation.
