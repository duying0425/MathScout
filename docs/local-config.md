# Local Configuration

Last updated: 2026-06-05.

For the current development plan, see
[Development Roadmap](development-roadmap.md).

MathScout reads runtime configuration from `.env`.

## Default Local Setup

Use `.env.example` to create a local `.env`:

```powershell
Copy-Item .env.example .env
```

The default local `.env` should be intentionally simple:

```text
DATABASE_URL=sqlite+pysqlite:///./.data/mathscout_dev.db
AI_PROVIDER=rule
DEEPSEEK_API_KEY=
```

`.env` is ignored by Git so local keys are not committed.

This SQLite mode requires no Docker, no Redis, and no PostgreSQL. It is enough for:

- importing the textbook template
- creating crawl jobs
- running one-process crawls
- storing fetched documents, candidates, methods, variants, and decisions
- opening the database-backed admin UI and Web Agent Console
- testing the DB-backed runtime, including `crawl_tasks.not_before` delayed
  scheduling

The SQLite database file lives under `.data/` and is local-only. After cloning in
a new environment, run the initialization commands again:

```powershell
mathscout init-db
mathscout import-template
mathscout seed-sources
```

`mathscout init-db` and app startup call `ensure_database_schema()`, which keeps
current local additive schema changes such as `crawl_tasks.not_before` available.
This is not a replacement for Alembic once PostgreSQL migrations become serious.

The admin dashboard and list pages use the same `DATABASE_URL` setting as the
CLI, so switching from SQLite to PostgreSQL changes both surfaces together.

## Admin and Agent Console

Run the app on the original local port:

```powershell
uvicorn mathscout.main:app --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000/admin/agent
```

The Agent Console accepts the goal and URL in one text box. For example:

```text
请帮我抓取http://www.example.com/test下的数据
```

This extracts `http://www.example.com/test` and creates the crawl job from the
conversation. Hidden defaults keep `extractor_mode=auto`, link discovery on, and
auto-start on unless the backend strategy changes them.

## Crawler User Agent

`DEFAULT_USER_AGENT` is used as the HTTP `User-Agent` header for crawler
requests and for `robots.txt` permission checks. It is not an API key.

Changing this value can affect crawling behavior because some sites filter,
rate-limit, or vary responses based on user agent. Keep it descriptive for real
public crawls.

## DeepSeek

To use DeepSeek through the OpenAI-compatible API, set:

```text
AI_PROVIDER=deepseek
DEEPSEEK_API_KEY=your_deepseek_key
OPENAI_COMPATIBLE_BASE_URL=https://api.deepseek.com
OPENAI_COMPATIBLE_MODEL=deepseek-chat
```

If `AI_PROVIDER=rule`, the crawler uses the local rule-based extractor and does
not call an external AI API.

If `extractor_mode=auto`, MathScout uses AI only when the configured provider
and API key are available. Otherwise it falls back to deterministic local logic.

## PostgreSQL Later

PostgreSQL is optional for the first version. Use it later when you need:

- larger datasets
- concurrent workers
- stronger query performance
- pgvector semantic search

With Docker Desktop running, use:

```powershell
docker compose up -d postgres redis
```

Then use `.env.postgres.example` as the configuration reference.

Docker Desktop on Windows can run these Linux containers through its WSL backend.
You do not need to install a separate Ubuntu/Debian WSL distribution just for
this project, as long as Docker Desktop itself is working.
