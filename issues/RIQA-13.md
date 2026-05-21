# RIQA-13: Plan tab: Outlook card shows contradictory "Not supported / Ok" status when tanks critically fail to meet target autonomy days

**Jira:** [RIQA-13](https://acfuture-inc.atlassian.net/browse/RIQA-13)
**Type:** Bug | **Status:** To Do | **Priority:** Medium
**Assignee:** Aishwarya Hoonur | **Labels:** NewIssue
**Created:** 2026-05-16 | **Updated:** 2026-05-16

## Description

Steps to Reproduce:

1. Navigate to https://ac-future-water.elevatics.site/
2. Set Expert count = 4
3. Set Fresh Tank Capacity = 20 gal, Current Fresh Level = 15 gal
4. Set Target Autonomy Days = 14
5. Click Save & Compute, navigate to the Plan tab
6. Read the Outlook card

Expected Result:

When the fresh water runway (0.37 days) is dramatically shorter than the 14-day target, the Outlook card should show a clear critical/failure state — not an ambiguous or contradictory message.

Actual Result:

* Outlook card reads "Not supported Ok" (with a checkmark) — contradictory: "Not supported" implies failure, but the checkmark and "Ok" signal acceptability.
* Fresh tank runway is 0.37 days against a 14-day target — a 97% deficit. Daily fresh usage is 41.00 gal with only 15 gal available.
* API stability_score confirms: status = "Not supported", score_pct = 2.6% — yet the UI footer shows a checkmark.
* A user could mistake the checkmark-Ok footer for a pass/approval indicator and plan a 14-day trip that would run out of fresh water on day 1.
