# MathScout

MathScout is an AI-managed knowledge-base app for junior high school math. Its
main value is collecting diverse problem-solving techniques from teachers,
preserving useful variants, and mapping them to the right textbook chapters,
sections, and knowledge points. Backend agents plan, crawl, extract, reconcile,
monitor quality, and decide when to continue or stop. Human users supervise
through dashboards and natural-language direction.

The main backend function is AI-assisted knowledge reconciliation: every newly
crawled resource is converted into candidate knowledge items, compared with the
existing database, and then skipped, updated, created, marked as conflict, or
sent to human review.

The intended control model is AI-led orchestration with hard system guardrails:
AI manages scheduling, strategy, execution, quality monitoring, and stop
conditions; humans adjust direction, inspect quality, approve risky changes, and
communicate with the AI in natural language.

The first dataset shape is based on `.template/beishida_math_json_v3_with_template`.

## Core Goals

- Track textbook versions, books, chapters, sections, and cross-semester links.
- Crawl public resources first, then handle login-gated sources with user-provided cookies.
- Extract:
  - curriculum-standard knowledge points
  - teacher guide and lesson-design methods
  - problem-solving techniques
  - common student skills
  - evidence snippets and source provenance
- Treat teacher problem-solving techniques as first-class canonical data.
- Preserve different teacher variants instead of over-merging useful approaches.
- Map every technique to textbook version, chapter, section, knowledge point, task pattern, and prerequisite skill.
- Let backend AI agents reconcile new candidates against existing database records.
- Let the AI orchestrator create tasks, reprioritize sources, monitor quality, and decide continue/pause/stop.
- Let users steer the system with natural-language commands and visual dashboards.
- Auto-skip clear duplicates and keep source/last-seen metadata fresh.
- Propose updates or new records with evidence and confidence.
- Route ambiguous or conflicting candidates to a review queue.
- Store normalized data in SQLite for local first runs, with PostgreSQL available for larger crawls.
- Provide a simple admin UI for crawl jobs, source documents, extraction review, and data quality.

## Proposed Stack

- Backend API and admin: FastAPI, Jinja templates, HTMX-ready server-rendered pages.
- Database: SQLite for local runs; PostgreSQL, SQLAlchemy, Alembic, optional pgvector for scale.
- Queue: Redis plus Celery workers.
- Crawling: httpx for static pages, Playwright for JavaScript and login sessions.
- Parsing: trafilatura and BeautifulSoup for HTML, PyMuPDF for PDF.
- Extraction: schema-constrained LLM extraction plus deterministic validators.

## Local Development

Use Python 3.11 or newer. Python 3.14.5 has been smoke-tested on this machine.

The local default uses SQLite and does not require Docker.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
mathscout init-db
mathscout import-template
mathscout seed-sources
uvicorn mathscout.main:app --reload
```

Configuration is read from `.env`. A local `.env` is already created with SQLite:

```text
DATABASE_URL=sqlite+pysqlite:///./.data/mathscout_dev.db
AI_PROVIDER=rule
DEEPSEEK_API_KEY=
```

When cloning in a new environment, create it from the example:

```powershell
Copy-Item .env.example .env
```

To enable DeepSeek / OpenAI-compatible AI extraction, edit `.env`:

```text
AI_PROVIDER=deepseek
DEEPSEEK_API_KEY=your_deepseek_key
OPENAI_COMPATIBLE_BASE_URL=https://api.deepseek.com
OPENAI_COMPATIBLE_MODEL=deepseek-chat
```

PostgreSQL and Redis are optional for later scale. With Docker Desktop running:

```powershell
docker compose up -d postgres redis
```

Then switch `.env` to the value in `.env.postgres.example`.

Worker:

```powershell
celery -A mathscout.worker.celery_app worker -l info
```

Admin UI:

```text
http://127.0.0.1:8000/admin
```

## First Crawl Flow

```powershell
mathscout init-db
mathscout import-template
mathscout seed-sources
mathscout crawl-url "https://example.com/some-public-math-teaching-page" --extractor auto
```

Persistent crawl jobs:

```powershell
mathscout create-job --name "public-teacher-pages" --url "https://example.com/page1" --url "https://example.com/page2"
mathscout run-job "<job_id>" --extractor auto
mathscout stop-job "<job_id>"
mathscout job-status "<job_id>"
```

`stop-job` pauses the job in the database. A running `run-job` process checks
that status between URLs, so completed pages stay persisted and remaining tasks
wait in `pending`. Running `run-job` again resumes a paused job.

For quick local testing without Docker/PostgreSQL:

```powershell
mathscout init-db
mathscout import-template
```

The first crawler version writes:

- fetched page/PDF metadata to `source_documents`
- parsed text to `.data/text`
- evidence snippets to `evidence_snippets`
- AI or rule-based teaching-method candidates to `candidate_knowledge_items`
- canonical methods and teacher variants to `teaching_methods` and `teaching_method_variants`
- audit decisions to `reconciliation_decisions`

See [docs/first-version-pipeline.md](docs/first-version-pipeline.md) for current limits.
See [docs/development-status.md](docs/development-status.md) for handoff status and next steps.

## First Milestone

1. Import the existing `.template` JSON into the normalized tables.
2. Add seed source sites:
   - Ministry of Education curriculum standards and textbook catalog.
   - National Smart Education Platform public course and textbook metadata.
   - Provincial and city education bureau teaching-book notices.
   - Public lesson plans, micro-lessons, and teacher research articles.
3. Crawl metadata and small public documents only.
4. Extract and review one textbook series end to end.

See [docs/architecture.md](docs/architecture.md) for the full design.
