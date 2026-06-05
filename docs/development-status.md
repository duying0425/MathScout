# Development Status

Last updated: 2026-06-05.

For the detailed work plan, see
[Development Roadmap](development-roadmap.md).

## Current Working State

MathScout has a runnable first version focused on collecting teacher
problem-solving techniques and storing them under textbook structure and
knowledge points.

Implemented:

- SQLite-first local configuration through `.env`
- optional DeepSeek/OpenAI-compatible extraction
- textbook template import from `.template`
- source-site seeding
- database-backed admin dashboard counts
- admin knowledge browser backed by textbook, chapter, section, and knowledge-point tables
- admin list pages backed by source, crawl job, document, review, change, command, and technique tables
- single URL crawling
- persistent DB-backed crawl jobs
- stop/resume behavior through job status
- HTML/PDF parsing
- source document and evidence storage
- AI or rule-based method candidate extraction
- LLM-first multi-agent control plane for command interpretation, orchestration planning,
  source selection, execution monitoring, and reconciliation
- admin AI command flow that lets the NaturalLanguageCommandAgent interpret goals before
  creating orchestration sessions and crawl jobs
- web Agent Console at `/admin/agent` with a chat-style timeline and JSON
  message API backed by existing command/session/decision/job tables
- simplified Agent Console composer with one human goal input; crawl strategy
  settings now use backend defaults instead of visible form controls
- Agent Console goals can include inline URLs, including Chinese-attached text
  such as `请帮我抓取http://www.example.com/test下的数据`
- seed-page link discovery with AI source selection and deterministic policy guardrails
- execution monitoring decisions that can continue, pause, stop, request review, or patch strategy
- documented agent runtime contract for tasks, tools, hooks, observations, and review actions
- first `CrawlJobRunner` split into scheduler, task executor, runtime hooks, and recorder components
- before-fetch runtime checks for URL validity, source access policy, robots, crawl delay,
  and review-item creation when a task requires human review
- schema-backed delayed scheduling through `crawl_tasks.not_before`, with
  Web status polling triggering due pending jobs to resume without in-worker sleep
- after-fetch runtime checks for HTTP failures, login gates, unsupported content,
  empty pages, and short boilerplate/error pages
- `CrawlPipeline.crawl_url()` compatibility wrapper now delegates to explicit
  `fetch_url`, `parse_document`, `extract_methods`, and `reconcile_candidate`
  internal tool methods
- `crawl_tasks.result_json` normalization that preserves legacy UI fields while
  adding stable observation fields for runtime monitoring
- `ReviewService` runtime tool boundary for candidate/review-item
  approve/reject/needs-edit actions and audit-log writes
- unified admin navigation shared across dashboard, command, jobs, review, list, and detail pages
- canonical teaching method creation
- teacher/source method variant creation
- basic method-to-knowledge-point and method-to-section inference
- AI-first reconciliation decision audit records with threshold fallback

Not implemented yet:

- real admin edit forms
- admin detail pages and filtering/search
- Playwright login-cookie flow
- Postgres migrations with Alembic
- vector search / pgvector
- independent always-on worker orchestration outside the current Web polling tick
- durable multi-step agent state beyond DB tasks and audit logs

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
http://127.0.0.1:8000/admin/agent
```

The CLI remains useful for local setup, imports, smoke tests, and emergency job
control. Product-facing human-Agent interaction should use the web Agent
Console rather than CLI commands.

The admin UI uses the same `DATABASE_URL` as the CLI. In the default SQLite
setup, the dashboard should show the imported template data after initialization:

- `Knowledge`: 425
- `Source Sites`: 3

The knowledge page shows 1 textbook series, 6 books, 34 chapters, 127 sections,
425 knowledge points, and 16 student skills from the imported template.

## Handoff Notes

`.env` and `.data/` are local-only and are not committed. In a new environment,
copy `.env.example` to `.env`, add any private API keys manually, then run:

```powershell
mathscout init-db
mathscout import-template
mathscout seed-sources
```

Do not expect the local SQLite database from this machine to exist after clone.
The template import recreates the baseline textbook data.

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

If `AI_PROVIDER=rule`, or if no API key is configured, the control plane and
extractor use local deterministic fallbacks. With DeepSeek/OpenAI-compatible
configuration, command interpretation, orchestration planning, source selection,
execution monitoring, reconciliation, and extraction use schema-constrained LLM
agents where wired.

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
ruff check mathscout tests
pytest
```

Latest full test run: 44 tests passed.

SQLite smoke test also passed:

- create schema
- import template
- create crawl job
- run job against `https://example.com`
- query job status

## Recommended Next Work

1. Persist fetch/parse/extract/reconcile as explicit DB task types:
   task payload validators, executor dispatch, step observations, retry/resume
   tests, and crawl-job step timeline UI.
2. Add quality-check tasks:
   source-yield metrics, duplicate/skip rate, review backlog, stop conditions,
   and strategy patches.
3. Add review/edit workflows:
   review detail page, evidence preview, candidate edit before approval,
   canonical method/variant edit forms, mapping edits, and human-lock policy.
4. Add Playwright/cookie-profile access:
   domain-scoped storage state, blocked-login review UI, expiration handling,
   and no captcha/paywall bypass.
5. Add retrieval/vector support:
   SQL retrieval first, pgvector/embedding path later, richer reconciliation
   context, and conflict routing.
6. Add an independent always-on worker when Web-polling-driven due ticks are no
   longer enough:
   DB task claiming, per-domain concurrency, and clean shutdown/resume behavior.
