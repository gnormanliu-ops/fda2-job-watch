"""Publish daily changes to GitHub Issues without exceeding issue body limits.

Job data is already committed before this script runs. This script never edits it.
Large reports are chunked into issue body + bot comments.
"""
import csv
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DAY = datetime.now(timezone.utc).date().isoformat()
MARKER = "<!-- fda-job-watcher-automated-part -->"
MAX_CHARS = 42000


def gh(*args, input_text=None):
    cmd = ["gh", *args]
    result = subprocess.run(cmd, input=input_text, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"GitHub command failed: {' '.join(cmd[:5])}: {result.stderr[-1200:]}")
    return result.stdout.strip()


def post_body_argument(body, cmd):
    """Use a temporary file instead of passing a long body on command line."""
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as tmp:
        tmp.write(body)
        filename = tmp.name
    try:
        return gh(*cmd, "--body-file", filename)
    finally:
        Path(filename).unlink(missing_ok=True)


def line_for(row):
    label = f"{row['employer']}: {row['title']}".replace("\n", " ").replace("\r", " ")
    # Avoid breaking Markdown links when a job title contains a closing bracket.
    label = label.replace("[", "\\[").replace("]", "\\]")
    url = (row.get("url") or "").strip()
    return f"- [{label}]({url})" if url.startswith("https://") else f"- {label} (link unavailable)"


def chunk_sections(new, removed, source_lines):
    sections = [
        ("New", new),
        ("Removed", removed),
    ]
    lines = [f"# Daily job changes — {DAY}", "", f"New: {len(new)} · Removed: {len(removed)}", ""]
    for label, rows in sections:
        lines += [f"## {label} ({len(rows)})", ""]
        lines += [line_for(r) for r in rows] if rows else ["- None"]
        lines.append("")
    lines += ["## Source status", ""] + source_lines
    pages = []
    part = []
    length = 0
    for line in lines:
        # Individual absurdly long source titles are bounded to prevent one
        # Markdown entry exceeding GitHub's issue/comment body size limit.
        if len(line) > MAX_CHARS - 1000:
            line = line[:MAX_CHARS - 1010] + "…"
        cost = len(line) + 1
        if part and length + cost > MAX_CHARS:
            pages.append("\n".join(part))
            part, length = [], 0
        part.append(line)
        length += cost
    if part:
        pages.append("\n".join(part))
    return pages


def main():
    with (ROOT / "data/history.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    status = json.loads((ROOT / "data/status.json").read_text())
    new = [r for r in rows if r["first_seen"] == DAY and r["first_run"] == "false"]
    gone = [r for r in rows if r["removed_date"] == DAY]
    source_lines = [
        f"- {s['name']}: {'OK' if s['ok'] else 'FAILED'} "
        f"({s.get('count', 0)} jobs){' — ' + s['error'] if s.get('error') else ''}"
        for s in status["sources"]
    ]
    pages = chunk_sections(new, gone, source_lines)
    issues = json.loads(gh("issue", "list", "--state", "all", "--limit", "100",
                           "--json", "number,title,state"))
    existing = next((i for i in issues if i["title"] == DAY), None)
    if existing:
        number = str(existing["number"])
        post_body_argument(pages[0], ("issue", "edit", number))
        if existing["state"] == "CLOSED":
            gh("issue", "reopen", number)
    else:
        gh("issue", "create", "--title", DAY, "--body", pages[0])
        issues = json.loads(gh("issue", "list", "--state", "all", "--limit", "100",
                               "--json", "number,title,state"))
        existing = next((i for i in issues if i["title"] == DAY), None)
        if not existing:
            raise RuntimeError("Daily issue was created but could not be looked up")
        number = str(existing["number"])

    # Re-runs must replace automated extra pages, not duplicate them.
    repo = os.environ.get("GITHUB_REPOSITORY", "gnormanliu-ops/fda2-job-watch")
    existing_comments = json.loads(
        gh("api", "--paginate", f"repos/{repo}/issues/{number}/comments?per_page=100")
    )
    for comment in existing_comments:
        if MARKER in (comment.get("body") or ""):
            gh("api", "-X", "DELETE",
               f"repos/{repo}/issues/comments/{comment['id']}")

    for i, page in enumerate(pages[1:], start=2):
        post_body_argument(f"{MARKER}\n\n## Part {i} of {len(pages)}\n\n{page}",
                           ("issue", "comment", number))

    for issue in issues:
        if (issue["title"] != DAY and issue["state"] == "OPEN"
                and re.fullmatch(r"\d{4}-\d{2}-\d{2}", issue["title"])):
            gh("issue", "close", str(issue["number"]))

    print(f"Daily issue {number}: {len(new)} new, {len(gone)} removed, "
          f"{len(pages)} report part(s)")


if __name__ == "__main__":
    main()
