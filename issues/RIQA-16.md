# RIQA-16: Alert threshold set to 100% suppresses all alerts — no warnings fire even when usage is 51% above baseline

**Jira:** [RIQA-16](https://acfuture-inc.atlassian.net/browse/RIQA-16)
**Type:** Bug | **Status:** To Do | **Priority:** Medium
**Assignee:** Aishwarya Hoonur | **Labels:** NewIssue
**Created:** 2026-05-16 | **Updated:** 2026-05-16

## Description

Steps to Reproduce:

1. Navigate to https://ac-future-water.elevatics.site/
2. Set Expert count = 2, Fresh Capacity = 100 gal, Current Fresh = 80 gal
3. Set Alert threshold (%) = 100 in Section 2
4. Set Behavioral Drift slider to maximum (1.0 / 100%)
5. Click Save & Compute, then navigate to the Realtime tab
6. Observe whether any alert banners appear on any of the days

Expected Result:

An alert threshold of 100% should mean: "alert when daily usage exceeds 100% above baseline" (i.e., more than 2x the normal amount). Days that deviate by less than 100% should not fire, but a threshold of 100% should still be reachable.

Actual Result:

* NO alerts fire on ANY day, regardless of how large the usage deviation is.
* Confirmed with drift at maximum: Day 1 showed +51.7% above baseline (20 gal baseline vs 30.34 gal actual) — alert = false.
* The stored value for threshold=100 is 1.0 (confirmed via GET /api/inputs: alert_threshold = 1.0).
* The alert logic appears to use the stored fraction as a multiplier directly (alert when usage > baseline \* (1 + threshold)), meaning threshold=1.0 requires 200%+ daily usage to trigger — effectively impossible under normal conditions.
* As a result, setting alert threshold to 100% silently disables all alerts, with no indication to the user.
