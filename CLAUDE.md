# MathScout — Claude Code Guide

## Project Overview
MathScout is an AI-managed knowledge-base maintenance system for Chinese math education.
It crawls teaching resources, uses AI to extract teaching methods, and maintains a curated knowledge base.

**Scope is being upgraded to a 4-dimension knowledge graph** (design locked, build pending — see
[docs/knowledge-graph-redesign.md](docs/knowledge-graph-redesign.md)):
- **Textbook / chapter / section** — version-dependent; only decides teaching order & selection.
- **Knowledge points** — version-independent, canonical (shared across all textbook versions).
- **Problems** (题目) — version-independent, weakly linked to sections; LaTeX stems, optional answers/figures.
- **Solving techniques** (解题技巧/模型, = `teaching_methods`) — reusable across problems.

Guiding principle: **textbooks are views; knowledge points and problems are the stable facts.**
A solution (解答) is problem-specific and is NOT the same as a technique (reusable model).

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
- **markitdown** — unified document → Markdown conversion (Office, scanned PDF/image OCR via Azure Document Intelligence). Type detection + conversion live in `mathscout/parsers/{detect,convert,attachments}.py`. See `docs/ingestion.md`. Lazy-imported, so HTML/digital-PDF paths work without it.

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
| `/admin/problems` | Problem library (list); `/admin/problems/<id>` detail — stem, solutions+techniques, tested knowledge points (confirm/reject AI tagging), weakly-linked sections, figures |
| `/admin/review` | Pending review queue |
| `/admin/agent` | Agent: create crawl jobs via natural-language objective (AI-planned, decisions logged) |

## Crawl Job Modes

- **Targeted** (default): crawl exactly the URLs provided, one task per URL.
- **Deep crawl** (`discover_links=true`): after each page, extract same-domain links under the same URL path prefix as the seed, add as new tasks. Prevents full-site crawl.

## Important Conventions

- All DB timestamps stored as naive UTC; display converts to UTC+8 via `_display()` in routes.py.
- `cards` variable removed from dashboard route — was dead code.
- `pipeline_status` enum: `crawled | extracted | done | failed | login_required | needs_ocr` (`needs_ocr` = scanned PDF/image awaiting OCR when Azure Document Intelligence is not configured)
- Scrapling `Response.body` always returns `bytes`; no need for `isinstance(raw, str)` check.
- **Knowledge-graph redesign (in progress):** `knowledge_points` is being decoupled from a single `section` (drop the `section_id` hard binding → `section_knowledge_point_links` M:N; `semantic_key` becomes content-based so the same KP dedups across textbook versions). New tables `problems` / `solutions` / `figures` + link tables; `CandidateItemType` gains `problem` / `solution`. Build order: **Phase A (KP canonical-ization) first** — lowest risk, independent of crawling problems. Full plan: [docs/knowledge-graph-redesign.md](docs/knowledge-graph-redesign.md).
