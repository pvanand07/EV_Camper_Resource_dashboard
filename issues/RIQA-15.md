# RIQA-15: Realtime tab: Greywater recycling reports 0 gal recycled on Day 1 when grey tank starts at full capacity

**Jira:** [RIQA-15](https://acfuture-inc.atlassian.net/browse/RIQA-15)
**Type:** Bug | **Status:** To Do | **Priority:** Medium
**Assignee:** Aishwarya Hoonur | **Labels:** NewIssue
**Created:** 2026-05-16 | **Updated:** 2026-05-16

## Description

Steps to Reproduce:

1. Navigate to https://ac-future-water.elevatics.site/
2. Set Expert count = 2, Fresh Capacity = 100 gal, Current Fresh = 80 gal
3. Set Grey Tank Capacity = 30 gal, Current Grey Level = 30 gal (tank already full at trip start)
4. Enable the Greywater Recycling toggle
5. Click Save & Compute, navigate to the Realtime tab
6. Inspect Day 1 data (or call /api/realtime directly and check days\[0\].grey_recycled_gal)

Expected Result:

When the grey tank is already full at trip start (30/30 gal) and recycling is enabled, the existing grey water should be available for recycling into toilet flushing on Day 1. grey_recycled_gal for Day 1 should be > 0, and fresh water used for toilet flushing should be reduced accordingly.

Actual Result:

* API /api/realtime Day 1 returns grey_recycled_gal = 0, even though the grey tank starts full (30/30 gal) and recycling is enabled.
* Grey tank level at end of Day 1 is 30.0 / 30 gal — it remains full, indicating the starting grey water was neither recycled nor treated as overflowing.
* Toilet fresh consumption on Day 1 is 4.40 gal (full fresh-water usage for toilet), confirming no grey recycling was applied.
* The recycling logic appears to only consider grey water added during the current day, ignoring pre-existing grey water in the tank on Day 1.
