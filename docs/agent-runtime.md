# Agent Runtime

Last updated: 2026-06-05.

For the overall implementation roadmap, see
[Development Roadmap](development-roadmap.md).

MathScout should use an agent runtime model, not a collection of ad hoc agent
calls. The goal is to keep the AI useful while making every action bounded,
auditable, resumable, and reviewable.

This document is the implementation contract for the next refactor. It borrows
from mature coding-agent patterns such as explicit tools, subagents, hooks,
memory/state, and structured observations. It does not depend on Claude Code
source code and should not clone any closed implementation.

## Runtime Shape

Every autonomous unit of work should follow the same loop:

```text
human goal or queued task
  -> interpret scope and constraints
  -> plan next action
  -> call one deterministic tool
  -> observe structured result
  -> decide continue / retry / pause / review / stop
  -> persist task state, artifacts, decisions, and audit records
  -> run post-action hooks
```

The runtime owns state transitions. Agents return structured decisions. Tools
execute concrete work. Agents should not directly mutate unrelated database
records outside the tool contract they are invoked through.

## Interaction Surface

The primary human-Agent surface should be the web Agent Console, not the CLI.
The CLI can remain as a developer and maintenance entrypoint for local setup,
smoke tests, imports, and emergency job control.

The web surface should provide:

- a chat-like command stream for human goals and Agent responses
- JSON APIs for sending goals and reading the current Agent timeline
- links into task detail, review, documents, and decisions
- live status updates without forcing the user into status tables first

The current first slice is `/admin/agent` plus `/admin/agent/messages`, backed
by the existing `natural_language_commands`, `orchestration_sessions`,
`agent_decisions`, and `crawl_jobs` tables. No separate message table is needed
until multi-turn memory, threaded conversations, or per-message attachments
become necessary.

The default composer intentionally exposes only one human goal input. Source
selection, discovery breadth, extractor choice, and auto-start behavior are
strategy defaults that the command/planner agents may revise and the operator
can later inspect through tasks and decisions.

## Current Mapping

| Runtime concept | Current table/module |
| --- | --- |
| Session memory | `orchestration_sessions` |
| User command | `natural_language_commands` |
| Plan/audit event | `agent_decisions` |
| Queue item | `crawl_tasks` |
| Queue group | `crawl_jobs` |
| Tool artifact | `source_documents`, `.data/raw`, `.data/text` |
| Extraction artifact | `extraction_runs`, `candidate_knowledge_items` |
| Reconciliation artifact | `reconciliation_decisions` |
| Human gate | `review_items`, review status fields |
| Human action audit | `manual_edit_logs` |

Existing modules already approximate the runtime:

| Runtime role | Current implementation |
| --- | --- |
| Command interpreter | `NaturalLanguageCommandAgent` |
| Planner | `AIOrchestratorAgent` / `OrchestratorPlanningAgent` |
| Source selector | `SourceDiscoveryAgent` and `SourceSelectionAgent` |
| Policy gate | `PolicyGuardAgent`, login detection, HTTP checks |
| Tool executor | `HttpFetcher`, `CrawlPipeline`, parsers, extractors |
| Monitor | `ExecutionMonitorAgent` |
| Review operator | admin review routes |

The missing piece is a clear runtime boundary around task execution. Today
`CrawlJobRunner` both schedules tasks, invokes agents/tools, applies monitor
decisions, mutates job state, and creates review records. That works for a
first version but will become hard to reason about once extraction, search,
reconciliation, login cookies, and quality monitoring all become multi-step.

## Principles

### 1. AI Chooses, Tools Execute

Agents decide what should happen next. Tools perform the action.

Examples:

- `SourceSelectionAgent` may choose URLs from candidates.
- `HttpFetcher` actually downloads a URL.
- `AIMethodExtractor` turns parsed text into schema-constrained candidates.
- `ReviewActionTool` marks a candidate approved/rejected and writes audit logs.

### 2. No Hidden Side Effects

Each tool must declare what it can write.

Examples:

- `fetch_url` may write raw/text files and `source_documents`.
- `discover_links` may create `crawl_tasks` and `agent_decisions`.
- `extract_methods` may write `extraction_runs`, evidence, and candidates.
- `apply_review_action` may update review status and `manual_edit_logs`.

If a tool needs to touch a new table, update this document and add a regression
test for the write path.

### 3. Structured Observations

Tool results should be JSON-serializable observations with stable fields:

```json
{
  "status": "succeeded",
  "artifact_ids": [],
  "metrics": {},
  "warnings": [],
  "error": null,
  "retryable": true,
  "requires_review": false
}
```

`crawl_tasks.result_json` should store this observation. UI rendering should
read from stable fields instead of guessing from free-form agent payloads.

### 4. Hooks Are Deterministic Gates

Hooks are code-level policy checks before or after a tool call. They should not
ask the AI for permission.

Required hooks:

- `before_fetch`: scheme/domain/access policy, robots, rate limit, disabled source.
- `after_fetch`: HTTP status, login gate, content type, empty/boilerplate page.
- `before_extract`: document size, source type, duplicate checksum, extractor budget.
- `after_extract`: schema validity, candidate count, confidence distribution.
- `before_apply`: review policy, human lock, destructive-change guard.
- `after_task`: write monitor observation and create review item if needed.

### 5. Review Is Part of Runtime

Review is not a separate afterthought. Any agent/tool can request review by
returning `requires_review=true` with a reason and target.

Review items should include:

- target table and id
- reason
- source task/job/session
- proposed action or observed problem
- enough payload for a human to understand the decision

Approving/rejecting a review item is itself a tool call that writes
`manual_edit_logs`.

## Task Types

The current string task types should become stable runtime task types:

| Task type | Purpose | Main tool | Writes |
| --- | --- | --- | --- |
| `discover_links` | Fetch seed page and select child URLs | source discovery | `crawl_tasks`, `agent_decisions` |
| `crawl_url` | Fetch, parse, extract, reconcile one URL | crawl pipeline | documents, candidates, methods, variants |
| `extract_document` | Re-run extraction for an existing document | extractor | extraction runs, candidates |
| `reconcile_candidate` | Compare one candidate with canonical data | reconciliation | reconciliation decisions, review items |
| `quality_check` | Measure current output and source yield | quality monitor | quality snapshots, agent decisions |
| `review_action` | Apply human approval/rejection/edit status | review tool | review status, manual edit logs |

Only the first two are wired today. The others should be added as explicit task
types instead of hidden inside `crawl_url` once the workflow grows.

## State Transitions

Valid task status transitions:

```text
pending -> running
running -> succeeded
running -> failed
running -> blocked
running -> paused
failed -> pending      when retryable and retry budget remains
blocked -> pending     when user retries after policy/config change
pending/running -> cancelled
```

Terminal job status is derived from task counts unless a monitor explicitly
pauses or stops the job:

- any `failed` task beyond retry budget -> job `failed`
- any `blocked` task -> job `blocked`
- all tasks succeeded -> job `succeeded`
- manual stop -> job `paused`
- manual cancel -> job `cancelled`

## Agent Contracts

### Command Agent

Input:

- raw human command
- form defaults
- available source URLs
- current source summaries

Output:

- interpreted intent
- target scope
- strategy preferences
- budgets
- stop conditions
- review policy

It must not create jobs directly.

### Planner

Input:

- directive
- orchestration context
- active source and quality snapshot

Output:

- ordered actions
- rationale
- policy requirements
- expected outcomes
- risk notes

The executor turns plan actions into DB tasks and audit records.

### Source Discovery Agent

Input:

- seed URL
- objective
- allowed max links
- external-link policy

Output:

- selected child links
- rejected links or policy reasons
- discovery metrics
- observation status

It can only select URLs from fetched page candidates. It cannot invent URLs.

### Extraction Agent

Input:

- document URL
- parsed text
- target textbook scope

Output:

- schema-constrained candidates
- evidence snippets
- confidence and warnings

It must not write canonical records directly.

### Reconciliation Agent

Input:

- candidate
- retrieved matches
- manual edit history for matched records

Output:

- `skip`, `update`, `create_variant`, `create`, `conflict`, or `review`
- rationale
- proposed patch
- confidence
- review requirement

Low-risk decisions can be applied automatically only when policy allows it.

### Execution Monitor

Input:

- current job and task
- last observation
- task counts and budget usage

Output:

- `continue`, `pause_job`, `stop_job`, `request_review`, or `adjust_strategy`
- rationale
- optional strategy patch

The monitor should not create crawl tasks directly. It can request a strategy
patch that the runtime applies and audits.

## Tool Contracts

Tools should be small, deterministic wrappers around code. A tool may call an AI
agent internally only when the tool name says it is an AI-backed action, such as
`select_links_with_ai` or `extract_methods_with_ai`.

Recommended first tool registry:

| Tool | Inputs | Outputs |
| --- | --- | --- |
| `fetch_url` | URL, source policy | `FetchObservation` |
| `parse_document` | raw path, content type | `ParseObservation` |
| `discover_links` | seed URL, objective, max links | `DiscoveryObservation` |
| `create_crawl_tasks` | source task, selected links | `TaskCreationObservation` |
| `extract_methods` | document id, text path, mode | `ExtractionObservation` |
| `reconcile_candidate` | candidate id | `ReconciliationObservation` |
| `monitor_task` | job id, task id, observation | `MonitorObservation` |
| `apply_review_action` | target, action, reason | `ReviewObservation` |

The next code refactor should not introduce a heavy framework first. Start with
plain Python functions/classes and typed Pydantic observation models. Add a graph
runner only if the DB-backed queue becomes hard to maintain.

## Prompt and Model Rules

All AI-backed agents must:

- receive compact structured context
- return JSON validated by Pydantic
- fail closed to deterministic fallback or review
- never receive raw full-page content when a parsed/chunked excerpt is enough
- never invent URLs, source facts, textbook mappings, teachers, or schools
- include rationale that can be written to `agent_decisions`

Prompts should live close to their agent, but output schemas should live in code.

## Implementation Plan

### Phase A: Runtime Documentation and Contracts

Status: active.

- Add this document.
- Add stable observation schemas in `mathscout/runtime.py`.
- Add tests for login/public-page detection, blocked task retry, and route status APIs.
- Keep current admin behavior working.

### Phase B: Split `CrawlJobRunner`

Status: started.

Refactor without changing behavior:

- `JobScheduler`: prepare/resume jobs and pick next task.
- `TaskExecutor`: execute one task and return observation.
- `RuntimeRecorder`: persist status, observations, decisions, and review items.
- `RuntimeHooks`: pre/post deterministic gates.

`CrawlJobRunner` should become a coordinator that delegates to these pieces.

Current code has introduced the first three components in
`mathscout/pipeline/jobs.py`:

- `CrawlJobScheduler`
- `CrawlTaskExecutor`
- `CrawlRuntimeRecorder`
- `CrawlRuntimeHooks` with the first `before_fetch` gate

`CrawlPipeline` now also performs first-pass `after_fetch` checks for HTTP
failures, login-gated pages, unsupported content types, empty pages, and short
boilerplate/error pages. These results keep the current legacy `status` values
for UI compatibility while adding observation-style fields such as
`runtime_status`, `requires_review`, `review_reason`, `metrics`, and `payload`.

Task results now pass through `normalize_task_result()` before being stored in
`crawl_tasks.result_json`. The normalizer preserves legacy root fields for the
current admin UI and adds stable observation fields for the runtime and Agent
monitor.

Review actions now go through `ReviewService`, which is a runtime tool boundary
for candidate/review-item approve, reject, and needs-edit actions. Admin routes
call the service, and future Agent tools can call the same service.

Crawler rate delay now uses `crawl_tasks.not_before` rather than sleeping inside
the worker. The Agent Console and crawl-job status APIs trigger a lightweight
due-job tick during Web polling, so already-started pending jobs can resume when
their next task becomes due.

The next slice is to persist those step-level tools as separate task types.

### Phase C: Split Crawl Pipeline

Turn the current `crawl_url` mega-step into explicit tools:

```text
fetch_url -> parse_document -> extract_methods -> reconcile_candidate -> monitor_task
```

Status: started. `CrawlPipeline.crawl_url()` is still the UI/CLI-compatible
wrapper, but it now delegates to `fetch_url`, `parse_document`,
`extract_methods`, and `reconcile_candidate` methods internally. The next step
is to persist these as separate DB task types so failures and retries can resume
at step level.

### Phase D: Real Quality and Review Runtime

- Add `quality_check` tasks.
- Add review detail pages and edit forms.
- Add source yield metrics and stop-condition enforcement.
- Add human-lock behavior to reconciliation decisions.

### Phase E: External Tool Compatibility

Once local contracts are stable, expose tools through MCP-style interfaces or a
thin local tool registry. This makes browser fetching, search, vector retrieval,
and external document tools replaceable without changing agent prompts.

## Anti-Patterns to Avoid

- Letting an LLM write directly to canonical tables without a tool contract.
- Mixing planning, execution, persistence, and review in one function.
- Adding a graph framework before the task/result contracts are stable.
- Treating every failed crawl as an AI problem instead of a policy/tool
  observation.
- Hiding important state in prompt text instead of database records.
- Using review as a static list rather than a runtime action with audit logs.

## Immediate Code Targets

1. Persist `fetch_url`, `parse_document`, `extract_methods`, and
   `reconcile_candidate` as DB task types instead of only internal methods.
2. Add quality-check tasks and source-yield metrics.
3. Add review detail/edit pages backed by `ReviewService`.
4. Add Playwright/cookie-profile fetching for user-authorized login sources.
5. Add vector retrieval for richer reconciliation matches.

Detailed next implementation checklist:

- Add task payload validators for each new task type.
- Update `CrawlTaskExecutor.execute()` to dispatch explicit step tasks.
- Keep `crawl_url` as a compatibility task that expands into step tasks.
- Add tests for resuming after fetch success but parse/extract failure.
- Render step-level task timelines in crawl job detail pages.
- Add a `quality_check` task after each batch and after crawl-delay resumes.
- Keep monitor decisions from overriding deterministic failed/blocked task
  counts.
