# FDA Job Watcher

[![Tests](https://github.com/gnormanliu-ops/fda2-job-watch/actions/workflows/tests.yml/badge.svg)](https://github.com/gnormanliu-ops/fda2-job-watch/actions/workflows/tests.yml)

Public Financial Data Analytics course project. Daily job-board snapshots with Python, GitHub Actions, three GitHub Pages views and a PWA.

**Coverage:** The project tracks 20 legacy Workday employers plus five experimental public API candidates (SmartRecruiters: AECOM, Western Digital, Sandisk; Greenhouse: DoorDash and Robinhood). The five candidates are NOT counted as verified until they produce a valid response. The five previously unconfigured employers (NVIDIA, Tesla, Ford Motor, Cummins, Nike) remain removed. A source is counted as successful only when its JSON request succeeds. A successful request does not prove that the job board returned every vacancy. H-1B application history does not imply sponsorship of any particular vacancy.

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
- `sources.json`: 25 employer configurations, provider adapters, candidate states, and backup settings
- `job_watcher.py`: Workday / Greenhouse / SmartRecruiters JSON collection, normalization, deterministic history reconstruction
- `backup_sources.py`: employer-by-employer optional licensed secondary search and historical snapshot fallback; neither counts as an official successful collection
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
Every tracked employer and its ATS state is listed in `sources.json`. All 20 configured sources have returned JSON, though exactly 40 jobs on several boards warrants a completeness review. CVS Health, Walmart, and Target use `search_term: analyst`, so those snapshots cover that search term rather than their complete job boards. The Workday JSON endpoint is `https://HOST/wday/cxs/TENANT/SITE/jobs`; collection is paginated. If a board has over 5,000 results, set `search_term` and document it here. Never scrape HTML as a fallback.

## Required GitHub setup
In repository Settings → Pages choose **GitHub Actions**. Enable Actions workflow write permissions and Issues. Trigger the Daily job watch workflow once and inspect source failures. The instructor requires at least seven separate UTC dates with successful raw snapshots; a completed Actions job with zero successful feeds is not a data-success day. Check Blackboard for first-run and submission deadlines. Daily runs may be delayed by GitHub scheduling.


## Multi-ATS resilience and backup sources

The 20 historical Workday feeds remain unchanged. Additional Greenhouse and SmartRecruiters clients have independent 429 cooldowns, so a rate limit on one ATS must not block the others. A feed is only successful if it returns valid JSON and an entire snapshot is saved. Candidate feeds have not yet been confirmed in GitHub Actions.

Every configured employer has two fallback mechanisms: a dated **last successful raw snapshot** (always available after a first successful collection; explicitly marked historical), and an optional **Headcount Labs** secondary job discovery query. The latter is **not active by default** and must not be portrayed as a verified substitute for an official full job board. It is a partial finance-related search and will not update `data/raw`, `history.csv`, `new_today`, `removed_today`, or `days_with_success`.

The secondary service requires a valid `HEADCOUNT_API_KEY` repository secret, `ENABLE_LICENSED_BACKUP=true` repository variable, and a review of the provider license and attribution requirements before publication. Without those, the dashboard explicitly says **API authorization required**, rather than claiming a fresh backup feed. Historical snapshots are not fresh job updates. See https://headcountlabs.com/license/ and https://headcountlabs.com/docs/jobs/.

The daily scheduled collection remains the only automatic collection trigger; code pushes run tests and Pages deployment but do not start extra data collection.