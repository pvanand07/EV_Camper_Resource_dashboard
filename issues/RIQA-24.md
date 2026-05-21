# RIQA-24: Realtime tab: Black tank starting at full capacity overflows silently every day with no warning or alert

**Jira:** [RIQA-24](https://acfuture-inc.atlassian.net/browse/RIQA-24)
**Type:** Bug | **Status:** To Do | **Priority:** Medium
**Assignee:** Cooper | **Labels:** NewIssue
**Created:** 2026-05-16 | **Updated:** 2026-05-16

## Description

Steps to Reproduce:

1. Navigate to https://ac-future-water.elevatics.site/
2. Set Expert count = 2, Fresh Capacity = 100 gal, Current Fresh = 80 gal
3. Set Black Tank Capacity = 30 gal, Current Black Level = 30 gal (tank already full)
4. Set Target Autonomy Days = 5
5. Click Save & Compute, then navigate to the Realtime tab
6. Observe Day 1 black tank level and any alert banners

Expected Result:

When the black tank starts full, the Realtime tab should immediately alert the user that the tank will overflow from Day 1. An alert banner should appear and the overflow should be flagged.

Actual Result:

* Realtime Day 1 shows black tank level = 30.0 / 30 gal (capped), with 3.6 gal/day being added to an already-full tank.
* The 3.6 gal daily black water overflow is silently discarded — it does not appear as a warning or separate overflow indicator.
* No alert banner fires for the black stream on Day 1 (alert_black = false), despite the tank being at 100% capacity on the first day of the trip.
* The Plan tab does show "0.00 days" runway and a "Dump Soon!" status for Black, but the Realtime tab provides no equivalent real-time overflow warning.
