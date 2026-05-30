# RIQA-37: Input Validation: Target Autonomy Days accepts decimal values (step=1 stepMismatch validation bypassed)

**Jira:** [RIQA-37](https://acfuture-inc.atlassian.net/browse/RIQA-37)
**Type:** Bug | **Status:** To Do | **Priority:** Medium
**Assignee:** Cooper | **Labels:** NewIssue
**Created:** 2026-05-21 | **Updated:** 2026-05-21

## Description

Environment: v0.3 | Browser: Chromium (headless) | OS: Linux (Ubuntu)

Preconditions:

1. Navigate to https://ac-future-water.elevatics.site/
2. Select version v0.3 from the version picker.
3. The Input tab is active by default.

Steps to Reproduce:

1. In Section 1, set Expert count to 2.
2. In Section 2 — Tank & Environment, locate the "Target Autonomy Days" field.
3. Note the field has step="1" and min="1" (integer-only per the HTML attribute).
4. Clear the field and type a decimal value, e.g. "7.5".
5. Observe the field value is now "7.5" and HTML5 validity reports stepMismatch=true with message "Please enter a valid value. The two nearest valid values are 7 and 8."
6. Observe the "Save & Compute" button remains ENABLED (not disabled).
7. Click "Save & Compute".
8. Observe the API call succeeds (HTTP 200) and the value 7.5 is persisted.
9. Reload the page — the Target Autonomy Days field retains 7.5.

Expected Result:

The "Save & Compute" button should be disabled (or an inline validation error should be shown) when the Target Autonomy Days field contains a decimal value, since the field specifies step="1" (integer-only). The value should not be saved to the API until corrected.

Actual Result:

* The "Save & Compute" button remains enabled despite the HTML5 stepMismatch validation error.
* The decimal value (e.g. 7.5) is submitted in the PUT /api/inputs payload as-is: {"target_autonomy_days": 7.5}.
* The API accepts and persists the decimal value. The field still shows 7.5 after save and after page reload.
* The user receives no validation error or warning — the fractional autonomy target is silently accepted.

Reproducibility: Reproduced 100% of the time. Confirmed with values 7.5 and 14.7.
