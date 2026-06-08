# MathScout

MathScout 是一个面向**初中数学**的、由 AI 辅助维护的教学知识库系统。它的核心价值是
从公开教研资料中收集教师的解题方法与教学讲法，保留不同老师的有价值变体，并把它们
映射到对应的教材版本、章节、小节与知识点。

与普通爬虫不同，MathScout 把抓取只当作输入层，真正的产出是一个**可溯源、可人工
复核**的教师方法知识库：每一条新抓取的资料都会被转换成候选知识项，与已有库记录
比较后，再决定跳过、更新、创建、标记冲突或转人工复核。

> **关于 "AI 编排"**：项目的长期目标是让后端 AI 负责规划、调度、调和与质量监控，
> 人工只做方向把控与复核。但**当前版本的编排与链接打分是基于规则的确定性逻辑，
> 尚未接入 LLM 推理**；AI（DeepSeek / OpenAI 兼容接口）目前只用于 Phase 2 的方法
> 抽取，且有规则抽取器兜底。文档中凡涉及多 Agent、自动策略调整等内容均为**规划**，
> 实现状态请以 [docs/development-status.md](docs/development-status.md) 为准。

## 三阶段流水线

```
Phase 1（爬取）   → 本地文件      （pipeline_status = 'crawled'）
Phase 2（提取）   → 候选知识项     （pipeline_status = 'extracted'）
Phase 3（复核）   → 入库知识库     （pipeline_status = 'done'）
```

每个阶段都可独立重跑，`source_documents.pipeline_status` 是阶段间的交接信号。
改了 Prompt 或换了模型，只需把目标文档状态改回 `crawled` 重跑 Phase 2 即可，
无需重新联网抓取。

## 核心目标

- 跟踪教材版本、册别、章节、小节，以及跨学期的衔接关系。
- 优先抓取公开资源；登录受限来源需在用户提供合法 Cookie 后才处理。
- 抽取：课程标准知识点、教师教学/教案方法、解题技巧、常见学生能力、证据片段与来源出处。
- 把教师解题方法当作**一等公民**数据，保留不同老师的讲法变体，避免过度合并。
- 把每个方法映射到教材版本、章节、小节、知识点、适用题型与前置能力。
- 自动跳过明显重复，保持来源与最近出现时间元数据更新。
- 带证据和置信度地提出更新或新建，把含糊/冲突的候选转入复核队列。
- 本地首跑用 SQLite，更大规模时可切换 PostgreSQL。
- 提供简洁的后台 UI，覆盖爬取任务、来源文档、抽取复核与数据概览。

## 技术栈

### 当前实现

- **后端 / 后台**：FastAPI + Jinja2 服务端渲染页面。
- **数据库**：默认 SQLite（本地零依赖）；SQLAlchemy ORM。迁移目前靠手写 `ALTER TABLE`。
- **抓取**：[Scrapling](https://github.com/D4Vinci/Scrapling) `AsyncFetcher`，自带反爬伪装。
- **解析**：HTML 用 trafilatura（BeautifulSoup 兜底），PDF 用 PyMuPDF。
- **抽取**：受 schema 约束的 LLM 抽取（DeepSeek / OpenAI 兼容接口），失败时回退规则抽取器。
- **后台任务**：FastAPI `BackgroundTasks`（在 web 进程内执行）。

### 规划中（尚未接入运行流程）

- PostgreSQL + Alembic 迁移；pgvector 向量检索。
- Playwright 渲染与登录 Cookie 流程。
- 独立 worker / 并发编排、按域限速与 robots 校验。
- LLM 驱动的编排与调和、质量监控与自动策略调整。

## 本地开发

需要 Python 3.11 或更高版本（本机用 3.14.5 做过冒烟测试）。本地默认用 SQLite，
**不需要 Docker**。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
mathscout init-db
mathscout import-template
mathscout seed-sources
uvicorn mathscout.main:app --reload
```

配置从 `.env` 读取。本地示例（SQLite + 规则抽取）：

```text
DATABASE_URL=sqlite+pysqlite:///./.data/mathscout_dev.db
AI_PROVIDER=rule
DEEPSEEK_API_KEY=
```

启用 DeepSeek / OpenAI 兼容抽取时，编辑 `.env`：

```text
AI_PROVIDER=deepseek
DEEPSEEK_API_KEY=你的_deepseek_key
OPENAI_COMPATIBLE_BASE_URL=https://api.deepseek.com
OPENAI_COMPATIBLE_MODEL=deepseek-chat
```

后台 UI：

```text
http://127.0.0.1:8000/admin
```

完成 `init-db`、`import-template`、`seed-sources` 后，控制台会显示真实计数，
知识库页面可浏览导入的教材结构。首份数据形态来自
`.template/beishida_math_json_v3_with_template`。

## CLI 命令

```powershell
# 初始化（仅首次）
mathscout init-db            # 创建数据库表
mathscout import-template    # 导入 .template 教材结构
mathscout seed-sources       # 写入默认来源站点

# Phase 1：爬取（只抓取，不调用 AI）
mathscout crawl-url "https://example.com/page"
mathscout create-job --name "公开教师页面" --url "https://example.com/a" --url "https://example.com/b"
mathscout run-job "<job_id>"      # stop-job 暂停后可再次 run-job 续跑
mathscout stop-job "<job_id>"
mathscout job-status "<job_id>"

# Phase 2：提取（AI 或规则）
mathscout extract-pending --limit 100 --extractor auto
mathscout extract-document "<document_id>" --extractor rule
```

`stop-job` 会把作业状态写为 `paused`。运行中的 `run-job` 会在每个 URL 之间检查该状态，
因此已完成的页面会保留，剩余任务停在 `pending`；再次 `run-job` 即可续跑。

抽取模式：`auto`（按 `.env` 配置）、`rule`（快速，不调 AI）、`ai`（DeepSeek）。
若 `AI_PROVIDER=rule` 或 `auto` 模式下没有 API Key，会自动使用本地规则抽取器。

## 后台页面

| 路径 | 用途 |
|------|------|
| `/admin` | 控制台 —— 三步工作流入口 |
| `/admin/agent` | 智能爬取（Agent）：用一句话目标创建受监督爬取任务（规则编排，决策可追溯）|
| `/admin/crawl-jobs` | 爬取任务列表与管理 |
| `/admin/crawl-jobs/<id>` | 任务详情、子任务与文档明细 |
| `/admin/sources` | 来源站点配置 |
| `/admin/documents` | 已抓取文档（失败/需登录可重新抓取）|
| `/admin/review` | 待复核队列 |
| `/admin/techniques` | 教学方法库 |
| `/admin/knowledge` | 教材结构知识库 |
| `/admin/decisions` | Agent 决策记录 |
| `/admin/changes` | 人工变更记录 |

## 爬取模式

- **定向**（默认）：精确抓取所给 URL，每个 URL 一个任务。
- **深度抓取**（`discover_links=true`）：每抓完一页，提取与种子同域、且 URL 路径前缀
  相同的链接，作为新任务加入，避免抓取整站。

## 更多文档

- 总体设计与愿景：[docs/architecture.md](docs/architecture.md)
- 三阶段流水线细节：[docs/first-version-pipeline.md](docs/first-version-pipeline.md)
- 当前实现状态与待办：[docs/development-status.md](docs/development-status.md)
- 数据模型：[docs/data-model.md](docs/data-model.md)
- 爬取与合规策略：[docs/crawl-policy.md](docs/crawl-policy.md)
- 本地配置说明：[docs/local-config.md](docs/local-config.md)
