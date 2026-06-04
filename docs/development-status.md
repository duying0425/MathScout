# Development Status

Last updated: 2026-06-04.

## Current Working State

MathScout has a runnable first version focused on collecting teacher
problem-solving techniques and storing them under textbook structure and
knowledge points.

Implemented:

- SQLite-first local configuration through `.env`
- optional DeepSeek/OpenAI-compatible extraction
- textbook template import from `.template`
- source-site seeding
- single URL crawling
- persistent DB-backed crawl jobs
- stop/resume behavior through job status
- HTML/PDF parsing
- source document and evidence storage
- AI or rule-based method candidate extraction
- canonical teaching method creation
- teacher/source method variant creation
- basic method-to-knowledge-point and method-to-section inference
- reconciliation decision audit records
- placeholder admin pages for dashboard, command center, techniques, knowledge, review, and changes

Not implemented yet:

- real admin edit forms
- full LLM reconciliation beyond extraction
- crawling link discovery from seed pages
- robots/rate-limit enforcement inside job runner
- Playwright login-cookie flow
- Postgres migrations with Alembic
- vector search / pgvector
- concurrent worker orchestration

## Local Run

Use Python 3.11 or newer. Python 3.14.5 was smoke-tested.

```powershell
cd C:\Users\duyin\Desktop\MathScout
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
mathscout init-db
mathscout import-template
mathscout seed-sources
uvicorn mathscout.main:app --reload
```

Admin UI:

```text
http://127.0.0.1:8000/admin
```

## DeepSeek

Edit `.env`:

```text
AI_PROVIDER=deepseek
DEEPSEEK_API_KEY=your_deepseek_key
OPENAI_COMPATIBLE_BASE_URL=https://api.deepseek.com
OPENAI_COMPATIBLE_MODEL=deepseek-chat
```

Run:

```powershell
mathscout crawl-url "https://example.com/public-math-teaching-page" --extractor auto
```

If `AI_PROVIDER=rule`, or if `auto` has no API key, the crawler uses the local
rule-based extractor.

## Persistent Jobs

```powershell
mathscout create-job --name "teacher-pages" --url "https://example.com/a" --url "https://example.com/b"
mathscout run-job "<job_id>" --extractor auto
mathscout stop-job "<job_id>"
mathscout job-status "<job_id>"
```

`stop-job` writes `paused` to the database. `run-job` checks status between URLs,
so completed pages remain stored and remaining tasks stay pending.

## Validation Performed

Commands run successfully in the local `.venv`:

```powershell
ruff check mathscout scripts tests
pytest -q
python -m compileall mathscout scripts tests
```

SQLite smoke test also passed:

- create schema
- import template
- create crawl job
- run job against `https://example.com`
- query job status

## Recommended Next Work

1. Add admin list/detail pages backed by database queries.
2. Add manual edit forms for `TeachingMethod`, `TeachingMethodVariant`, and mappings.
3. Add link discovery from seed source pages.
4. Wire `RobotsChecker` and per-domain crawl delays into `CrawlJobRunner`.
5. Add Playwright fetcher and cookie profile storage for login-gated sources.
6. Replace rule-based reconciliation with AI-assisted reconciliation using the existing candidate tables.
