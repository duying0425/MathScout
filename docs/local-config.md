# Local Configuration

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
- opening the admin UI

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
