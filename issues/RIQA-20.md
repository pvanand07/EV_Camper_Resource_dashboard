# RIQA-20: Version v0.1: Activity attribution column shows 0.0% for all activities but TOTAL row shows 100% in Results tab

**Jira:** [RIQA-20](https://acfuture-inc.atlassian.net/browse/RIQA-20)
**Type:** Bug | **Status:** Done | **Priority:** Medium
**Assignee:** Cooper | **Labels:** NonIssue
**Created:** 2026-05-16 | **Updated:** 2026-05-16

## Description

Steps to Reproduce:

1. Navigate to https://ac-future-water.elevatics.site/
2. Set any valid inputs (e.g. Expert = 2, Fresh Cap = 100 gal, Current Fresh = 80 gal)
3. Click Save & Compute
4. Use the version selector to switch to v0.1
5. Click the "Results" tab
6. Scroll down to the "Activity Engine — Daily Baseline" table and inspect the "Attrib %" column

Expected Result:

The Attrib % column should show the correct percentage attribution for each activity (e.g. Shower \~56%, Kitchen Sink \~31%, etc.), matching the values shown in the v0.3 Plan tab.

Actual Result:

* All individual activity rows in the Attrib % column show 0.0% (Shower: 0.0%, Kitchen Sink: 0.0%, Bathroom Sink: 0.0%, Toilet: 0.0%, Drinking: 0.0%).
* The TOTAL row at the bottom shows 100% — meaning all 100% is attributed to "total" but nothing is allocated to individual activities.
* The v0.1 Results tab also renders the Delta column header with garbled encoding: "Daily╬ö" instead of "Daily Δ" — a UTF-8/character encoding issue specific to v0.1.
* v0.3 Plan tab correctly shows individual attribution percentages for the same data, confirming this is a v0.1-specific display bug.
