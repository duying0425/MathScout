# Development Status

Last updated: 2026-06-08.

## 本次更新（中文，2026-06-08）

针对「后台界面交互逻辑混乱」的反馈，按三阶段流水线重新组织了 admin 导航与入口：

- **合并重复的 AI 指令入口**：`/admin/command`（结构化表单 + 指令/决策记录表格，
  通过 `AIOrchestratorAgent` 完整编排创建爬取任务）与 `/admin/agent`（聊天式
  UI，但模板引用的 `messages` / `jobs` 字段与路由实际返回的 `commands` /
  `decisions` 不匹配，初始页面与轮询接口均无法正常渲染——是个半成品/已损坏
  页面）功能高度重叠。删除了损坏的聊天界面路由（`agent_console` 旧版、
  `agent_messages`、`submit_agent_message`）与模板，将原 `/admin/command`
  路由与模板重命名为 `/admin/agent`，统一为「智能爬取 (Agent)」单一入口，
  归入 Phase 1。
- **顶部导航改为按阶段分组的二级结构**（`_header.html`）：一级导航为
  控制台 / Phase 1·爬取 / Phase 2·提取 / Phase 3·复核入库；二级子导航按
  所属阶段列出具体页面——爬取任务 / 智能爬取(Agent) / 来源站点 归入 Phase 1，
  已抓文档归入 Phase 2，复核队列 / 方法库 / 知识库 / 决策记录 / 变更记录
  归入 Phase 3——并根据当前路径前缀自动高亮所属阶段与子页面（含任务详情页
  这类带动态 ID 的路径）。
- **清理各模板重复/冲突的 `header`/`nav`/`.logo` 样式**：此前多数模板各自
  定义了一份不含 `.admin-brand`/`.admin-page-title`/`.admin-nav` 的通用
  `header{}` 规则，导致 `_header.html` 渲染出的导航在不同页面上样式不一致
  （部分页面的导航链接完全没有激活态高亮）；现统一改为引用
  `_shared_styles.html` 中的 `.admin-header`/`.admin-nav`/`.admin-subnav`，
  并新增二级子导航的样式定义。

已起本地开发服务器逐页验证全部 10 个后台路径（控制台、智能爬取、爬取任务、
任务详情、已抓文档、复核队列、方法库、知识库、来源站点、决策记录、变更记录）
均正常渲染（HTTP 200），导航分组归属与激活态高亮均符合预期；旧路径
`/admin/command` 已确认返回 404（已整体迁移，无需兼容重定向，因为是纯内部
后台工具且无外部书签依赖）。同时同步更新了 `CLAUDE.md` 中的页面路径文档。

## 此前更新（中文，2026-06-07）

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
- 后台导航按三阶段分组的二级结构（`/admin/agent` 统一 AI 指令入口，
  归并自此前重复且部分损坏的 `/admin/command` + 聊天式 `/admin/agent`）

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
7. Phase 2（提取）目前在二级导航中只挂了「已抓文档」一个页面——若后续需要
   单独查看「正在/待提取」批次历史或抽取日志，可以为 Phase 2 新增一个
   专属的提取记录页面，而不是只靠 `/admin/documents` 的 `pipeline_status` 列。
8. 二级子导航在窄屏（如移动端）下会换行堆叠，尚未做折叠/汉堡菜单适配；
   如果后台需要在小屏幕上使用，建议补充响应式收纳。

## 待确认事项（Open Questions）

- **`/admin/command` 旧路径是否需要兼容重定向**：本次直接将其迁移为
  `/admin/agent`（确认无外部书签/脚本依赖该路径，纯内部工具）。如果发现
  有自动化脚本或文档外链仍指向 `/admin/command`，需要补一条
  `RedirectResponse("/admin/agent")`。
- **「智能爬取 (Agent)」这个二级导航命名是否合适**：用于承载原
  `/admin/command` 的自然语言指令编排功能，如果团队内部已有更通用的叫法
  （如「AI 编排」「指令中心」），可以再调整 `_header.html` 中的 label 文案。
