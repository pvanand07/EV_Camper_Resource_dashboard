# RIQA-26: Error Handling: Save & Compute displays raw API JSON error when server-side input validation fails

**Jira:** [RIQA-26](https://acfuture-inc.atlassian.net/browse/RIQA-26)
**Type:** Bug | **Status:** To Do | **Priority:** Medium
**Assignee:** Cooper | **Labels:** NewIssue
**Created:** 2026-05-16 | **Updated:** 2026-05-16

## Description

Steps to Reproduce:

1. Navigate to https://ac-future-water.elevatics.site/ (v0.3)
2. Set Grey Tank Capacity to 30 gal
3. Set Current Grey Level to 99 gal (exceeds the 30-gal capacity)
4. Click Save & Compute
5. Observe the save bar message

Expected Result:

A clear, human-readable error message such as: "Grey tank level cannot exceed grey tank capacity." Field-level inline validation highlighting would be ideal.

Actual Result:

* The save bar renders the raw server JSON: Save failed: {"detail":\[{"type":"value_error","loc":\["body","tank_environment"\],"msg":"Value error, current_grey_gal (99.0) cannot exceed..."}\]}
* Technical JSON fields (loc, type, msg, ctx) are exposed directly in the consumer-facing UI.
* The client does not parse or localize the server validation error in any way.
* This occurs for grey, fresh, and black level-vs-capacity violations — any constraint that triggers a server-side Pydantic value_error.
