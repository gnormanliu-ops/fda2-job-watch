"""Employer-by-employer fallback: licensed secondary search + dated primary cache.

Secondary results are an explicitly limited, separate discovery dataset. They
never enter official raw snapshots, posting lifecycle, or successful-day totals.
"""
import gzip
import json
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlsplit

API = "https://api.headcountlabs.com/v1/jobs"
DOCS = "https://headcountlabs.com/docs/jobs/"
LICENSE = "https://headcountlabs.com/license/"
ATTRIBUTION = ("Job data: Headcount Labs (https://headcountlabs.com), ODbL 1.0. "
               "Job descriptions belong to their employers. Location data © "
               "OpenStreetMap contributors and Overture Maps.")
LIMIT = 50
TITLE_QUERY = 'analyst OR finance OR accountant OR controller OR treasury'


def name_key(name):
    return re.sub(r'\W+', '', str(name).casefold())


def value(obj):
    if isinstance(obj, dict) and obj.get("state") in ("known", "derived"):
        return obj.get("value")
    return None


def https_url(link):
    return isinstance(link, str) and urlsplit(link).scheme == "https" and bool(urlsplit(link).hostname)


def match_employer(row, source):
    company = row.get("company") or {}
    tickers = {str(x.get("value", "")).upper() for x in company.get("identifiers", [])
               if x.get("scheme") == "ticker"}
    if tickers:
        return source.get("ticker", "").upper() in tickers
    aliases = set(map(name_key, [source["name"], source["employer"]] +
                      source["fallback"].get("aliases", [])))
    return bool(aliases.intersection({name_key(company.get("name", "")),
                                      name_key(value(row.get("employer_name")) or "")}))


def search_secondary(client, source, key, now):
    params = {"company": source["fallback"]["company_query"],
              "title_advanced": TITLE_QUERY,
              "currentness": "current", "stale": "false", "limit": LIMIT,
              "fields": "job_id,currentness,stale,employer_name,title,postings,company",
              "include": "company"}
    response = client.get(API, params=params,
                          headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
                          timeout=95)
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("data")
    watermark = payload.get("snapshot_watermark")
    if not isinstance(rows, list) or not watermark:
        raise ValueError("Invalid backup JSON envelope")
    dt = datetime.fromisoformat(watermark.replace("Z", "+00:00"))
    if dt.tzinfo is None or not timedelta(minutes=-10) <= now-dt <= timedelta(hours=48):
        raise ValueError("Backup catalog is stale or has an invalid timestamp")
    result = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or not match_employer(row, source):
            continue
        if row.get("currentness") != "current" or row.get("stale") is not False:
            continue
        job_id = row.get("job_id")
        title = value(row.get("title"))
        if not job_id or not isinstance(title, str) or job_id in seen:
            continue
        # Only display a currently listed posting with a recent provider observation.
        for post in row.get("postings", []):
            if post.get("posting_status") != "listed":
                continue
            checked = post.get("last_completed_fetch_at")
            if not isinstance(checked, str):
                continue
            try:
                checked_dt = datetime.fromisoformat(checked.replace("Z", "+00:00"))
                if not timedelta(minutes=-10) <= now-checked_dt <= timedelta(hours=48):
                    continue
            except (ValueError, TypeError):
                continue
            link = value(post.get("application_url")) or value(post.get("posting_url"))
            if not https_url(link):
                continue
            attribution = post.get("attribution") or {}
            # Avoid redistributing entries with separate source-credit requirements.
            if attribution.get("required"):
                continue
            result.append({"job_id": job_id, "title": title, "url": link,
                           "underlying_ats": post.get("source", ""),
                           "last_verified_at": checked})
            seen.add(job_id)
            break
    return {"state": "secondary_available" if result else "no_verified_match",
            "provider": "Headcount Labs", "catalog_at": watermark,
            "scope": "Limited finance-related discovery, not a full employer board",
            "count": len(result), "sample_limit": LIMIT, "jobs": result}


def cached_snapshot(data, source, slug, today, primary_ok=False):
    files = sorted((data / "raw").glob("*/" + slug(source["name"]) + ".json.gz"),
                   reverse=True)
    for path in files:
        if path.parent.name >= today and not primary_ok:
            continue
        try:
            with gzip.open(path, "rt", encoding="utf8") as fh:
                raw = json.load(fh)
            if source.get("ats") == "greenhouse":
                count = len(raw["jobs"])
            elif source.get("ats") == "smartrecruiters":
                count = sum(len(p["content"]) for p in raw["pages"])
            else:
                count = len(raw["jobPostings"])
            return {"state": "saved_snapshot" if primary_ok else "historical_only",
                    "date": path.parent.name, "count": count,
                    "path": "data/raw/" + path.parent.name + "/" + path.name}
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return {"state": "no_snapshot"}


def collect_backups(data, configs, results, day, slug, make_session):
    # Explicit opt-in is required before publishing an independently licensed database.
    key = os.environ.get("HEADCOUNT_API_KEY", "").strip()
    allowed = os.environ.get("ENABLE_LICENSED_BACKUP", "").lower() == "true"
    client = None
    now = datetime.now(timezone.utc)
    rows = []
    by_name = {r["name"]: r for r in results}
    for src in configs:
        p = by_name.get(src["name"], {})
        fallback = src.get("fallback", {})
        cache = cached_snapshot(data, src, slug, day, bool(p.get("ok")))
        report = {"name": src["name"], "primary_ok": bool(p.get("ok")),
                  "cache": cache, "secondary": {"provider": "Headcount Labs"}}
        secondary = report["secondary"]
        if not fallback:
            secondary["state"] = "not_configured"
        elif p.get("ok"):
            secondary["state"] = "standby"
        elif not key or not allowed:
            secondary["state"] = "authorization_required"
        else:
            if client is None:
                client = make_session("headcount")
            if getattr(client, "rate_limit_stop", None):
                secondary["state"] = "deferred"
            else:
                try:
                    secondary.update(search_secondary(client, src, key, now))
                except Exception as exc:
                    # Never serialize credentials, URL parameters, or raw error bodies.
                    secondary.update(state="unavailable", error=type(exc).__name__)
        rows.append(report)
    return {"run_time": now.isoformat(), "scope": "Supplementary only; excluded from official statistics",
            "attribution": ATTRIBUTION, "license": LICENSE, "sources": rows}
