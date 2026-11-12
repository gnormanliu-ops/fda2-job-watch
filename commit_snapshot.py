"""Commit daily snapshots safely when main moves during collection.

Only collected raw snapshots are merged. Derived CSV/JSON files are always rebuilt
from the merged raw snapshots, so later commits cannot silently discard history.
"""
import argparse
import gzip
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import job_watcher as watcher

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"


def git(*args, check=True):
    return subprocess.run(
        ["git", *args], cwd=ROOT, text=True, capture_output=True, check=check
    )


def publish(max_attempts=5):
    git("config", "user.name", "github-actions[bot]")
    git("config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    status_path = DATA / "status.json"
    collection = json.loads(status_path.read_text())
    day = collection["run_time"][:10]
    today_dir = DATA / "raw" / day
    if not today_dir.is_dir():
        raise RuntimeError("No raw snapshot folder for this collection date")
    raw_files = list(today_dir.glob("*.json.gz"))
    if not raw_files:
        raise RuntimeError("No successful source snapshots found today")

    # Preserve the current run before synchronizing with the remote branch.
    with tempfile.TemporaryDirectory(prefix="fda-snapshot-") as tmp:
        backup = Path(tmp) / "raw"
        shutil.copytree(today_dir, backup)
        result = collection["sources"]

        for attempt in range(1, max_attempts + 1):
            git("fetch", "origin", "main")
            # The job only modifies generated data, never user source code.
            # Resetting to main prevents rebase conflicts with concurrent pushes.
            git("reset", "--hard", "origin/main")
            target = DATA / "raw" / day
            target.mkdir(parents=True, exist_ok=True)
            # Keep any snapshots already published by another run. Add or update
            # files that were successful in this particular run; failed sources
            # must not delete successful data committed by another run.
            for source in backup.glob("*.json.gz"):
                if not (target / source.name).exists():\n                    shutil.copy2(source, target / source.name)

            # The source summary must describe the raw files actually published.
            by_name = {watcher.slug(s["name"]): s for s in result}
            for name, source in by_name.items():
                saved = target / (name + ".json.gz")
                if saved.is_file() and not source["ok"]:
                    with gzip.open(saved, "rt", encoding="utf8") as fh:
                        jobs = json.load(fh).get("jobPostings", [])
                    source.update(ok=True, count=len(jobs))
                    source.pop("error", None)

            # Rebuild deterministically from the union of successful raw files.
            rows, dates = watcher.build()
            stat = dict(
                run_time=collection["run_time"],
                first_run_date=dates[0] if dates else "",
                days_with_success=len(dates),
                open=sum(r["status"] == "open" for r in rows),
                new_today=sum(r["first_seen"] == day and r["first_run"] == "false" for r in rows),
                removed_today=sum(r["removed_date"] == day for r in rows),
                sources=result,
            )
            status_path.write_text(json.dumps(stat, indent=2) + "\n")
            git("add", "data/raw", "data/history.csv", "data/status.json")

            if git("diff", "--cached", "--quiet", check=False).returncode == 0:
                print("Snapshots already present on origin/main; nothing to push")
                return

            git("commit", "-m", "Daily job snapshot " + day)
            push = git("push", "origin", "HEAD:main", check=False)
            if push.returncode == 0:
                print(f"Daily data pushed successfully on attempt {attempt}")
                return
            print(f"Push race on attempt {attempt}/{max_attempts}: {push.stderr[-500:]}")
            if attempt != max_attempts:
                time.sleep(attempt * 3)

    raise RuntimeError("Unable to push data after refreshing from origin/main")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempts", type=int, default=5)
    args = parser.parse_args()
    publish(args.attempts)
