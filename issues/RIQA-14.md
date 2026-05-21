# RIQA-14: Plan tab: Timeline Check displays "X days of headroom" when tank runway is actually a deficit (less than target, not a surplus)

**Jira:** [RIQA-14](https://acfuture-inc.atlassian.net/browse/RIQA-14)
**Type:** Bug | **Status:** To Do | **Priority:** Medium
**Assignee:** Aishwarya Hoonur | **Labels:** NewIssue
**Created:** 2026-05-16 | **Updated:** 2026-05-16

## Description

Steps to Reproduce:

1. Navigate to https://ac-future-water.elevatics.site/
2. Set Expert count = 2
3. Set Fresh Tank Capacity = 50 gal, Current Fresh Level = 50 gal
4. Set Target Autonomy Days = 10
5. Click Save & Compute, navigate to the Plan tab
6. Read the Timeline Check banner text

Expected Result:

The Timeline Check should communicate a deficit. Example: "Fresh tank runs out in 2.44 days — 7.56 days short of your 10-day target." The word "headroom" implies a buffer above the target.

Actual Result:

* The banner reads: "2.44 d of headroom vs. a 10-day target — Fresh tank is the constraint."
* "Headroom" is incorrect. The fresh tank only lasts 2.44 days, which is 7.56 days SHORT of the 10-day target — this is a deficit, not headroom.
* A user reading "2.44 d of headroom" may believe they have 2+ days of buffer above their 10-day trip, when they will actually run out of fresh water on day 2.
* The API correctly classifies this as Not Supported (score_pct = 24.4%), confirming the data is right but the UI copy is wrong.
