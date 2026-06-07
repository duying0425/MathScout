# First Version Pipeline

The pipeline is split into three independent phases. Each phase can be re-run
without rerunning the others.

## Phase 1 — Crawl (network I/O only, no AI)

Fetches URLs, saves raw files to disk, records metadata in `source_documents`.
Sets `pipeline_status = 'crawled'` on success.

```powershell
# Single URL
mathscout crawl-url "https://example.com/math-lesson"

# Via job (supports deep crawl with discover_links=true)
mathscout create-job --name "batch" --url "https://example.com/a" --url "https://example.com/b"
mathscout run-job "<job_id>"
```

### Deep Crawl Mode
When a job is created with `discover_links=true` (checkbox in the dashboard),
after each page is fetched the crawler extracts all same-domain links under the
same URL path prefix as the seed URLs, and adds them as new tasks. This prevents
crawling the entire site.

Example: seed `https://site.com/math/junior/index.html` → only follows links
under `/math/junior/`.

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
无需手动到「命令中心」重新提交。

## Phase 2 — Extract (AI or rules)

Reads local text files produced by Phase 1, runs extractors to create
`CandidateKnowledgeItem` records. Sets `pipeline_status = 'extracted'`.

```powershell
mathscout extract-pending --limit 100 --extractor auto
mathscout extract-document "<document_id>" --extractor rule
```

Extractor modes: `auto` (follow config), `rule` (fast, no AI), `ai` (DeepSeek).

## Phase 3 — Review & Reconcile

Human reviews candidates in `/admin/review`, approves/edits/rejects.
Approved items become canonical `TeachingMethod` entries.

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

## Admin UI Entry Point

The dashboard at `/admin` shows all three phases as a step-by-step workflow.
Start from Phase 1 by pasting URLs into the textarea.

## DB Initialization (first run only)

```powershell
mathscout init-db
mathscout import-template
mathscout seed-sources
```
