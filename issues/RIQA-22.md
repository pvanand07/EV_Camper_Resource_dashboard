# RIQA-22: Plan tab: "Refresh plan" button does not update the plan after input changes — unsaved edits are ignored

**Jira:** [RIQA-22](https://acfuture-inc.atlassian.net/browse/RIQA-22)
**Type:** Bug | **Status:** To Do | **Priority:** Medium
**Assignee:** Aishwarya Hoonur | **Labels:** NewIssue
**Created:** 2026-05-16 | **Updated:** 2026-05-16

## Description

Steps to Reproduce:

1. Navigate to https://ac-future-water.elevatics.site/
2. Set Expert count = 2, Fresh Capacity = 100 gal, Current Fresh = 80 gal
3. Click Save & Compute and navigate to the Plan tab — note the Fresh runway value
4. Return to the Input tab
5. Change Current Fresh Level from 80 to 20 (do NOT click Save & Compute)
6. Click the "Refresh plan" button in the save bar
7. Navigate to the Plan tab and observe whether the runway has updated

Expected Result:

Clicking "Refresh plan" should either (a) save the current inputs and recompute the plan, or (b) re-fetch the server-side plan. The Fresh runway should reflect the new 20-gal value.

Actual Result:

* After clicking "Refresh plan" with Fresh Level changed to 20 gal, the Plan tab still shows the old values computed from 80 gal.
* The "Refresh plan" button fetches the last saved plan from the server rather than the current unsaved inputs, with no indication to the user that unsaved changes are not reflected.
* There is no tooltip, disabled state, or warning to indicate that "Refresh plan" does not incorporate pending input changes.
* Users who change inputs and click "Refresh plan" (instead of "Save & Compute") will receive a plan based on stale data with no indication of the discrepancy.
