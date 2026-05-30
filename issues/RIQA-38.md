# RIQA-38: Input Validation: Blank current tank level field silently reuses old saved value — no error shown, no user feedback

**Jira:** [RIQA-38](https://acfuture-inc.atlassian.net/browse/RIQA-38)
**Type:** Bug | **Status:** To Do | **Priority:** Medium
**Assignee:** Cooper | **Labels:** NewIssue
**Created:** 2026-05-21 | **Updated:** 2026-05-21

## Description

Environment: v0.3 | Browser: Chromium (headless) | OS: Linux (Ubuntu)

Preconditions:

1. Navigate to https://ac-future-water.elevatics.site/ and select version v0.3.
2. Ensure at least one occupant is set (e.g. Expert = 2).
3. The Current Fresh Tank Level field has a saved value (default: 100 gal).

Steps to Reproduce:

1. In Section 2 — Tank & Environment, locate "Current Fresh Tank Level (gal)" (default value: 100).
2. Clear the field completely so it is empty (blank string "").
3. Observe: no validation error appears on the page, no inline error message is shown, and the "Save & Compute" button remains ENABLED.
4. Check the HTML5 validity of the field — it reports valid=true, valueMissing=false (no required attribute).
5. Click "Save & Compute".
6. Observe the API call succeeds (HTTP 200). The PUT /api/inputs payload contains current_fresh_gal: 100 (the previously saved value).
7. After save, the field repopulates with 100 — the blank entry was silently discarded and the old value reused.
8. The user receives no error, no warning, and no indication their blank input was ignored.

Expected Result:

Clearing a current tank level field to blank should either: (a) show an inline validation error requiring a value before allowing save, or (b) treat blank as 0 and explicitly display that. The user should receive clear feedback when a field they cleared is not accepted.

Actual Result:

* The blank Current Fresh Tank Level field passes all validation silently. No error or warning is shown.
* The Save & Compute button stays enabled and the form submits successfully.
* The API receives the previously saved value (100) rather than null or 0 — the blank input is silently discarded.
* The field repopulates with the old value after save, giving no feedback that the user's intent (to clear the field) was ignored.
* Same behavior confirmed for Current Grey Tank Level and Climate Multiplier fields.

Reproducibility: Reproduced 100% of the time across multiple fields (Current Fresh Tank Level, Current Grey Tank Level, Climate Multiplier).
