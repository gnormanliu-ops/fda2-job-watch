# FDA Job Watcher

[![Tests](https://github.com/gnormanliu-ops/fda2-job-watch/actions/workflows/tests.yml/badge.svg)](https://github.com/gnormanliu-ops/fda2-job-watch/actions/workflows/tests.yml)

Public Financial Data Analytics course project. Daily job-board snapshots with Python, GitHub Actions, three GitHub Pages views and a PWA.

**Caution:** 25 companies are candidate employers, not 25 verified working feeds. Ten preliminary Workday configurations are enabled; 15 remain disabled pending confirmation. A source is counted as successful only when its JSON request succeeds. H-1B application history does not imply sponsorship of any particular vacancy.

## Run locally
```bash
pip install -r requirements.txt
pytest -q
python job_watcher.py run
python job_watcher.py build
python -m http.server 8000
```
Browse to `http://localhost:8000/site/` locally. GitHub Pages publishes `site/` at root and includes `data/`.

## Files
- `sources.json`: 25 candidate employers, ATS settings and enablement
- `job_watcher.py`: JSON collection, normalization, deterministic history reconstruction
- `issue_report.py`: daily Issue updates
- `requirements.txt`: dependencies
- `tests/test_pipeline.py`: role, normalization and lifecycle tests
- `.github/workflows/tests.yml`: pytest on pushes
- `.github/workflows/daily.yml`: scheduled collection, data commit, daily issue
- `.github/workflows/pages.yml`: deploy three-page PWA
- `data/raw/YYYY-MM-DD/<source>.json.gz`: successful raw snapshots
- `data/history.csv`: normalized posting history (rebuilt solely from raw snapshots)
- `data/status.json`: UTC run metadata and per-source status
- `site/index.html`: Today; `site/browse.html`: Browse; `site/market.html`: Market
- `site/common.js`, `site/style.css`: shared UI
- `site/sw.js`, `site/manifest.webmanifest`, `site/icon.svg`: offline installation

## Title rule
Case-insensitive: financial analyst/planning/data, FP&A, finance analyst/manager/associate, cost analyst, business analyst, data analyst, risk analyst, investment analyst, operations analyst, treasury analyst, controller. All vacancies are retained even when they do not match.

## ATS sources
Every employer and its ATS state is listed in `sources.json`. Entries with `ats: unverified` are not yet usable sources. For the preliminary Workday entries, the endpoint is `https://HOST/wday/cxs/TENANT/SITE/jobs`; each needs a real successful paginated JSON test. If a board has over 5,000 results, set `search_term` and document it here. Never scrape HTML as a fallback.

## Required GitHub setup
In repository Settings → Pages choose **GitHub Actions**. Enable Actions workflow write permissions and Issues. Trigger the Daily job watch workflow once and inspect source failures. The instructor requires at least seven separate UTC dates with successful raw snapshots; a completed Actions job with zero successful feeds is not a data-success day. Check Blackboard for first-run and submission deadlines. Daily runs may be delayed by GitHub scheduling.
