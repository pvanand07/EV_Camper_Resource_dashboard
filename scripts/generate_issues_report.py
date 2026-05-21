"""Generate issue markdown files from Jira export JSON."""
import json
from pathlib import Path

RAW = Path(
    r"C:\Users\pvana\.cursor\projects\d-DEV-COOPER-EV-Camper-Resource-dashboard"
    r"\agent-tools\6733ff01-30ef-4b89-a668-26492ec25115.txt"
)
ROOT = Path(__file__).resolve().parent.parent
ISSUES_DIR = ROOT / "issues"

FRONTEND_ONLY = ["RIQA-13", "RIQA-14", "RIQA-20", "RIQA-22", "RIQA-26"]
FRONTEND_AND_BACKEND = [
    "RIQA-12", "RIQA-15", "RIQA-16", "RIQA-17", "RIQA-18", "RIQA-19",
    "RIQA-21", "RIQA-23", "RIQA-24", "RIQA-25", "RIQA-27", "RIQA-28",
    "RIQA-29", "RIQA-30",
]


def fmt_issue(issue: dict) -> dict:
    f = issue["fields"]
    assignee = f.get("assignee") or {}
    labels = ", ".join(f.get("labels") or [])
    key = issue["key"]
    return {
        "key": key,
        "summary": f["summary"],
        "type": f["issuetype"]["name"],
        "status": f["status"]["name"],
        "priority": f["priority"]["name"],
        "assignee": assignee.get("displayName", "Unassigned"),
        "labels": labels,
        "created": f["created"][:10],
        "updated": f["updated"][:10],
        "description": f.get("description") or "",
        "url": f"https://acfuture-inc.atlassian.net/browse/{key}",
    }


def issue_md(i: dict) -> str:
    lines = [
        f"# {i['key']}: {i['summary']}",
        "",
        f"**Jira:** [{i['key']}]({i['url']})",
        f"**Type:** {i['type']} | **Status:** {i['status']} | **Priority:** {i['priority']}",
        f"**Assignee:** {i['assignee']} | **Labels:** {i['labels'] or '—'}",
        f"**Created:** {i['created']} | **Updated:** {i['updated']}",
        "",
        "## Description",
        "",
        i["description"].strip(),
        "",
    ]
    return "\n".join(lines)


def report_md(title: str, keys: list[str], all_issues: list[dict], intro: str) -> str:
    by_key = {x["key"]: x for x in all_issues}
    lines = [
        f"# {title}",
        "",
        "Generated: 2026-05-21",
        "Source: [acfuture-inc.atlassian.net](https://acfuture-inc.atlassian.net) — RIQA-12 through RIQA-30",
        "",
        intro,
        "",
        f"**Total issues:** {len(keys)}",
        "",
        "## Summary Table",
        "",
        "| Key | Status | Priority | Summary |",
        "|-----|--------|----------|---------|",
    ]
    for k in keys:
        i = by_key[k]
        s = i["summary"].replace("|", "\\|")
        lines.append(f"| [{k}]({i['url']}) | {i['status']} | {i['priority']} | {s} |")
    lines.append("")
    for k in keys:
        i = by_key[k]
        lines.append("---")
        lines.append("")
        lines.append(issue_md(i))
    return "\n".join(lines)


def main() -> None:
    data = json.loads(RAW.read_text(encoding="utf-8"))
    ISSUES_DIR.mkdir(exist_ok=True)

    parsed = [fmt_issue(x) for x in data["issues"]]
    for i in parsed:
        (ISSUES_DIR / f"{i['key']}.md").write_text(issue_md(i), encoding="utf-8")

    fo_intro = (
        "Issues where the root cause is primarily in the UI layer — incorrect copy, "
        "display logic, or client-side error handling — and can be fixed without changing "
        "server/model behavior (though API data may already be correct)."
    )
    fb_intro = (
        "Issues requiring backend/model/API changes, often combined with frontend updates. "
        "Includes server-side validation gaps, water model logic bugs, alert/recycling "
        "calculations, and cases where both layers share responsibility."
    )

    (ISSUES_DIR / "frontend-only.md").write_text(
        report_md(
            "Frontend-Only Issues Report (RIQA-12–30)",
            FRONTEND_ONLY,
            parsed,
            fo_intro,
        ),
        encoding="utf-8",
    )
    (ISSUES_DIR / "frontend-and-backend.md").write_text(
        report_md(
            "Frontend & Backend Issues Report (RIQA-12–30)",
            FRONTEND_AND_BACKEND,
            parsed,
            fb_intro,
        ),
        encoding="utf-8",
    )

    print(f"Created {len(parsed)} individual issue files")
    print(f"frontend-only: {len(FRONTEND_ONLY)} issues")
    print(f"frontend-and-backend: {len(FRONTEND_AND_BACKEND)} issues")


if __name__ == "__main__":
    main()
