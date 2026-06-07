# Development Status

Last updated: 2026-06-07.

## 本次更新（中文，2026-06-07）

针对此前移植但未接通的功能与流水线缺口，完成并验证了以下三项开发：

- **复核操作接入 `/admin/review`**：原页面仍渲染只读的 `list.html`，`ReviewService`
  与 `review.html` 早已存在但从未连通。现已重写路由，渲染新模板并新增两个 POST
  路由（`/admin/review/candidates/{id}/{action}`、`/admin/review/items/{id}/{action}`），
  对接 `ReviewService.apply_candidate_action` / `apply_review_item_action`，
  实测「需编辑」操作可正确更新 `review_status` 并写入 `ManualEditLog`。
- **`not_before` 指数退避重试调度**：`CrawlTask.not_before` 列此前从未被读写。
  现已在 `CrawlJobRunner` 中接入：失败任务按 `30s * 2 ** (retries - 1)` 计算下次
  可重试时间并写入该列；调度循环优先挑选到期任务，对尚未到期的计划任务等待
  （上限 30 秒）后继续轮询，而非直接判定作业终态；达到 `max_retries`（默认 3）
  后任务保持失败终态。已用不可达 URL 实测验证：第 1 次失败后 30 秒重试，
  第 2 次失败后 60 秒重试，与公式完全吻合。
- **失败/需登录文档的重新抓取按钮**：此前没有任何针对 `pipeline_status =
  failed / login_required` 文档的重试入口（仅有一个未使用的展示文案占位
  `"retry_task": "重试任务"`）。现已在 `/admin/documents` 列表中为符合条件的
  文档新增「重新抓取」按钮，提交后通过 `CrawlJobRunner.create_job` 创建一个
  以该文档 URL 为种子的新抓取作业并立即在后台执行。同时为共享的 `list.html` /
  `_list_response` 增加了可选的按行操作列（`actions_enabled`），不影响其余
  仍使用旧版只读列表的页面。

详见 [first-version-pipeline.md](first-version-pipeline.md) 中「失败重试机制」
「失败文档重新抓取」「复核操作」三节。

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
- canonical teaching method creation
- teacher/source method variant creation
- basic method-to-knowledge-point and method-to-section inference
- reconciliation decision audit records
- 复核队列操作按钮（通过 / 需编辑 / 拒绝），接入 `ReviewService` 并写入 `ManualEditLog`
- 失败任务指数退避重试调度（`CrawlTask.not_before`）
- 失败 / 需登录文档的「重新抓取」入口（`/admin/documents`）
- crawling link discovery from seed pages（`discover_links=true` 深度抓取）

Not implemented yet:

- real admin edit forms
- admin detail pages and filtering/search
- full LLM reconciliation beyond extraction
- robots/rate-limit enforcement inside job runner
- Playwright login-cookie flow
- Postgres migrations with Alembic
- vector search / pgvector
- concurrent worker orchestration
- 跨阶段统一使用 `RuntimeObservation` / `normalize_task_result()`（目前仅 `review.py` 引用，
  `jobs.py` / `crawl.py` / `extract.py` 各自维护结果格式）
- `MonitorObservation` 驱动的来源策略自动调整（目前仅有类型定义，无具体实现）

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
ruff check mathscout tests
pytest
```

SQLite smoke test also passed:

- create schema
- import template
- create crawl job
- run job against `https://example.com`
- query job status

## Recommended Next Work

1. Add admin detail pages, filters, and search for textbook structure and crawl outputs.
2. Add manual edit forms for `TeachingMethod`, `TeachingMethodVariant`, and mappings.
3. Add link discovery from seed source pages.
4. Wire `RobotsChecker` and per-domain crawl delays into `CrawlJobRunner`.
5. Add Playwright fetcher and cookie profile storage for login-gated sources.
6. Replace rule-based reconciliation with AI-assisted reconciliation using the existing candidate tables.
