# RIQA-18: Alert threshold set to 0% fires alerts on every single day with any drift, making the alert system unusably noisy

**Jira:** [RIQA-18](https://acfuture-inc.atlassian.net/browse/RIQA-18)
**Type:** Bug | **Status:** To Do | **Priority:** Medium
**Assignee:** Cooper | **Labels:** NewIssue
**Created:** 2026-05-16 | **Updated:** 2026-05-16

## Description

Steps to Reproduce:

1. Navigate to https://ac-future-water.elevatics.site/
2. Set Expert count = 2, Fresh Capacity = 100 gal, Current Fresh = 80 gal
3. Set Alert threshold (%) = 0 in Section 2
4. Set Behavioral Drift slider to maximum (1.0 / 100%)
5. Click Save & Compute, then navigate to the Realtime tab
6. Observe the alert banners across all days

Expected Result:

A threshold of 0% should behave as "no threshold" or disable alerts entirely. Alternatively, it should be validated and rejected since 0% makes every day an alert day, rendering alerts meaningless.

Actual Result:

* Every single day fires alerts, including days with very minor deviations.
* Observed: Day 3 overall usage was -6.5% below baseline yet still fired an alert for Grey water usage at 60% more than usual.
* Day 1 fired alerts for Fresh (+21%), Grey (+8%), and Black (+11%) simultaneously — all three streams flagged at once.
* With threshold = 0 (stored as 0.0), any nonzero drift deviation triggers an alert, making it impossible to distinguish real water emergencies from normal daily variation.
* There is no validation or warning when the user sets threshold to 0%.
