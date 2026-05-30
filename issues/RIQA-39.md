# RIQA-39: Input Validation: Decimal occupant count (e.g. Expert = 1.5) silently truncated to integer — no validation error shown

**Jira:** [RIQA-39](https://acfuture-inc.atlassian.net/browse/RIQA-39)
**Type:** Bug | **Status:** To Do | **Priority:** Medium
**Assignee:** Cooper | **Labels:** NewIssue
**Created:** 2026-05-21 | **Updated:** 2026-05-21

## Description

Environment: v0.3 | Browser: Chromium (headless) | OS: Linux (Ubuntu)

Preconditions:

1. Navigate to https://ac-future-water.elevatics.site/ and select version v0.3.
2. The Input tab is active. Section 1 — People occupant count fields are visible.

Steps to Reproduce:

1. In Section 1 — People, locate the "Expert" occupant count field.
2. Note that the field has step="1" (integer-only per HTML attribute).
3. Clear the field and type a decimal value, e.g. "1.5".
4. Observe: the field shows "1.5". HTML5 validity reports stepMismatch=true with message "Please enter a valid value. The two nearest valid values are 1 and 2."
5. Observe: the "Save & Compute" button remains ENABLED despite the validation error.
6. Click "Save & Compute".
7. Observe: the API call succeeds (HTTP 200). The PUT /api/inputs payload contains {"name":"Expert","count":1,"is_child":0} — the value was truncated from 1.5 to 1.
8. After save, the Expert field updates to show "1" — the decimal was discarded silently.
9. No warning or error is shown anywhere on the page.

Expected Result:

When a decimal value is entered in an integer-only occupant count field (step=1), the form should either: (a) disable the Save & Compute button and show an inline validation error (consistent with how blank Tank Capacity fields are handled), or (b) round to nearest integer and explicitly notify the user. The user should not be able to unknowingly submit a value that gets silently truncated during computation.

Actual Result:

* The Expert count field accepts 1.5 and reports stepMismatch: true in HTML5 validation, but the Save & Compute button is NOT disabled.
* The form submits successfully. The PUT /api/inputs body sends count: 1 (not 1.5) — the frontend truncates the decimal before sending.
* The field updates to show "1" after save. The user receives zero feedback that their entered value of 1.5 was changed.
* The water consumption computation runs as if Expert count = 1, not 1.5, with no indication to the user.
* Affects all integer occupant fields: Expert, Typical, Glamper, Children (all have step="1").

Reproducibility: Reproduced 100% of the time. Confirmed with Expert=1.5 on two separate runs.
