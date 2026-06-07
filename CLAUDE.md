# MathScout — Claude Code Guide

## Project Overview
MathScout is an AI-managed knowledge-base maintenance system for Chinese math education.
It crawls teaching resources, uses AI to extract teaching methods, and maintains a curated knowledge base.

## Architecture: 3-Phase Pipeline

```
Phase 1 (crawl)    → local files  (pipeline_status = 'crawled')
Phase 2 (extract)  → DB candidates (pipeline_status = 'extracted')
Phase 3 (review)   → knowledge base (pipeline_status = 'done')
```

Each phase is independently re-runnable. `pipeline_status` on `source_documents` is the handoff signal.

## Key Tech

- **Scrapling** (`AsyncFetcher.get()`) — stealth HTTP fetching; response attrs are `.body` (bytes), `.status` (int), `.url` (str), `.headers` (dict), `.encoding` (str). NOT `.content`.
- **FastAPI + Jinja2** — server-rendered admin UI at `/admin`
- **SQLAlchemy + SQLite** — ORM, no Alembic (manual `ALTER TABLE` for migrations)
- **DeepSeek** — AI extraction in Phase 2

## Dev Server

```powershell
.venv\Scripts\uvicorn.exe mathscout.main:app --host 0.0.0.0 --port 8000 --reload
```

## CLI

```powershell
# Phase 1
.venv\Scripts\mathscout.exe crawl-url "https://example.com/page"

# Phase 2
.venv\Scripts\mathscout.exe extract-pending --limit 100 --extractor auto

# Jobs
.venv\Scripts\mathscout.exe run-job "<job_id>"
```

## Admin UI Pages

| Path | Purpose |
|------|---------|
| `/admin` | Dashboard — 3-step workflow entry point |
| `/admin/crawl-jobs` | Job list and management |
| `/admin/crawl-jobs/<id>` | Job detail, task/document breakdown |
| `/admin/documents` | All crawled documents |
| `/admin/techniques` | Teaching methods knowledge base |
| `/admin/review` | Pending review queue |
| `/admin/command` | Advanced: create jobs via natural language |

## Crawl Job Modes

- **Targeted** (default): crawl exactly the URLs provided, one task per URL.
- **Deep crawl** (`discover_links=true`): after each page, extract same-domain links under the same URL path prefix as the seed, add as new tasks. Prevents full-site crawl.

## Important Conventions

- All DB timestamps stored as naive UTC; display converts to UTC+8 via `_display()` in routes.py.
- `cards` variable removed from dashboard route — was dead code.
- `pipeline_status` enum: `crawled | extracted | done | failed | login_required`
- Scrapling `Response.body` always returns `bytes`; no need for `isinstance(raw, str)` check.
