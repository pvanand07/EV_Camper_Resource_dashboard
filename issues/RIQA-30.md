# RIQA-30: Children-only occupancy: adult activities (Shower, Kitchen Sink, Bathroom Sink) still compute full consumption with zero adult occupants

**Jira:** [RIQA-30](https://acfuture-inc.atlassian.net/browse/RIQA-30)
**Type:** Bug | **Status:** To Do | **Priority:** Medium
**Assignee:** Aishwarya Hoonur | **Labels:** NewIssue
**Created:** 2026-05-16 | **Updated:** 2026-05-16

## Description

Steps to Reproduce:

1. Navigate to https://ac-future-water.elevatics.site/ (v0.3)
2. Set Expert = 0, Typical = 0, Glamper = 0, Children = 2
3. Click Save & Compute
4. Check /api/results for Shower, Kitchen Sink, and Bathroom Sink daily_fresh_gal values

Expected Result:

With zero adult occupants, adult-profile activities should compute 0 gal/day. Only child-appropriate activities (Drinking (Children), etc.) should generate consumption.

Actual Result:

* With Children=2 and all adult types=0: Shower = 22.8 gal/day, Kitchen Sink = 9.0 gal/day, Bathroom Sink = 4.0 gal/day.
* These values match 2 Glamper-profile adults (Glamper shower mult=1.2: 1.9 gal/min × 5 min × 1 event × 2 persons × 1.2 = 22.8 gal), not children.
* Drinking (Children) = 0 gal and Drinking (Adults) = 0 gal — the children occupants are not mapped to any drinking activity.
* Children occupant count appears to feed Glamper-profile adult multipliers rather than a separate child activity profile, and children have no dedicated drinking consumption.
