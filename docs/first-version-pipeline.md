# 首版流水线（First Version Pipeline）

流水线分为三个相互独立的阶段，每个阶段都可单独重跑，无需重跑其他阶段。

## Phase 1 — 爬取（网络 I/O + 文档转换，不调用 LLM）

抓取 URL，把原始文件存到磁盘，在 `source_documents` 记录元数据。抓取后由摄取层做
**文档类型识别 + 转换**：HTML→trafilatura、数字版 PDF→PyMuPDF、Office→markitdown，
转成 Markdown 存到 `.data/text/<checksum>.md`。成功后将 `pipeline_status` 置为
`'crawled'`；扫描版 PDF/图片在未配置 Azure 文档智能时置为 `'needs_ocr'`。
详见 [ingestion.md](ingestion.md)。

> 注：此阶段的"AI"仅指扫描件/图片的 Azure OCR（可选）；教学方法的 LLM 抽取在 Phase 2。

```powershell
# 单个 URL
mathscout crawl-url "https://example.com/math-lesson"

# 通过作业（支持 discover_links=true 的深度抓取）
mathscout create-job --name "batch" --url "https://example.com/a" --url "https://example.com/b"
mathscout run-job "<job_id>"
```

### 深度抓取模式

当作业以 `discover_links=true` 创建（控制台里的复选框）时，每抓完一页，爬虫会提取
与种子 URL **同域、且 URL 路径前缀相同**的所有链接，作为新任务加入。这样可避免抓取
整站。

示例：种子 `https://site.com/math/junior/index.html` → 只跟进 `/math/junior/` 下的链接。

### 失败重试机制（指数退避）

`CrawlJobRunner` 会跟踪每个 `CrawlTask` 的 `retries` 与 `not_before` 字段：

- 任务失败时 `retries += 1`，并按 `retry_backoff_base_seconds * 2 ** (retries - 1)`
  （默认 30s 起步，即 30s → 60s → 120s …）计算下一次可重试时间，写入 `not_before`；
- 调度循环只挑选 `not_before` 为空或已到期的可运行任务；若暂时没有可运行任务但存在
  尚未到期的计划任务，会等待（最多 `max_wait_for_scheduled_task_seconds`，默认 30 秒）
  后继续轮询，而不是直接把作业判定为终态；
- 达到 `max_retries`（默认 3 次）后任务保持 `failed`，不再写入新的 `not_before`，
  作业随之进入终态。

### 失败文档重新抓取

当某篇 `source_documents` 的 `pipeline_status` 为 `failed` 或 `login_required`
时，`/admin/documents` 列表会出现「重新抓取」按钮（`POST /admin/documents/{document_id}/retry`）。
点击后会以该文档的 URL 创建一个新的单 URL 抓取作业并在后台立即执行，
无需手动到「智能爬取 (Agent)」重新提交。

## Phase 2 — 提取（AI 或规则）

读取 Phase 1 产出的本地文本文件，运行抽取器生成 `CandidateKnowledgeItem` 记录。
之后将 `pipeline_status` 置为 `'extracted'`。

```powershell
mathscout extract-pending --limit 100 --extractor auto
mathscout extract-document "<document_id>" --extractor rule
```

抽取模式：`auto`（按配置）、`rule`（快速，不调 AI）、`ai`（DeepSeek）。

## Phase 3 — 复核与调和

人工在 `/admin/review` 复核候选，进行 通过/编辑/拒绝。通过的项成为 canonical 的
`TeachingMethod` 记录。

### 复核操作（已接入 ReviewService）

`/admin/review` 列表中的「候选知识」与「监控复核项」每行都有「通过 / 需编辑 / 拒绝」
三个操作按钮，分别对应：

- `POST /admin/review/candidates/{candidate_id}/{approve|needs-edit|reject}`
- `POST /admin/review/items/{item_id}/{approve|needs-edit|reject}`

提交后由 `ReviewService.apply_candidate_action` /
`apply_review_item_action` 统一处理：更新对应记录的 `review_status`
（`approved` / `needs_edit` / `rejected`），并写入一条 `ManualEditLog`
记录复核理由与操作人，便于追溯。操作非法（如未知 action）时会回滚并
返回 400 错误提示。

## 后台 UI 入口

`/admin` 控制台把三个阶段呈现为一个分步工作流。从 Phase 1 开始：把 URL 粘贴进文本框即可。

## 数据库初始化（仅首次）

```powershell
mathscout init-db
mathscout import-template
mathscout seed-sources
```
