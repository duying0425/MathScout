# Development Roadmap

Last updated: 2026-06-05.

This document is the single planning view for MathScout development. Other docs
describe one slice of the system; this page summarizes the overall direction,
the current baseline, and the detailed work that should be expanded next.

## Product Direction

MathScout should become a supervised AI agent system for maintaining a junior
middle-school math teaching-method knowledge base.

The crawler is only the input tool. The main product loop is:

```text
human goal in Web Agent Console
  -> command interpretation and plan
  -> source discovery and crawl task creation
  -> deterministic tool execution
  -> structured observations
  -> extraction and reconciliation
  -> quality monitoring
  -> review/edit by human
  -> audited canonical knowledge updates
```

The primary human interface is the Web Agent Console at `/admin/agent`. The CLI
remains useful for local setup, imports, smoke tests, and emergency operations,
but product-facing interaction should not depend on CLI commands.

## Current Baseline

The current codebase has a runnable first agent loop:

- One-input Agent Console for human goals.
- Inline URL extraction from natural-language goals, including Chinese phrases
  such as `请帮我抓取http://example.com/test下的数据`.
- `auto` extractor mode by default: AI is used when `.env` enables an
  OpenAI-compatible provider and has a key; otherwise deterministic fallback is
  used.
- DB-backed crawl jobs and tasks.
- `discover_links` and `crawl_url` task types.
- Deterministic before-fetch checks for URL validity, source access level,
  robots, and crawl delay.
- Schema-backed deferred execution through `crawl_tasks.not_before`.
- Web polling-driven due-job tick so already-started pending jobs can continue
  after crawl delay without worker sleep.
- After-fetch checks for HTTP failures, login gates, unsupported content, empty
  text, and boilerplate pages.
- Stable runtime observation shape stored in `crawl_tasks.result_json`.
- `ReviewService` for candidate/review-item approve, reject, and needs-edit
  actions with audit logs.
- `CrawlPipeline.crawl_url()` remains the compatible entrypoint but internally
  delegates to `fetch_url`, `parse_document`, `extract_methods`, and
  `reconcile_candidate`.

## Architectural Decisions

- Prefer a simple DB-backed runtime before adding a heavy graph framework.
- Keep agents as decision-makers and tools as deterministic executors.
- Store every important observation, decision, artifact id, and review action in
  the database.
- Treat review as part of runtime, not as a detached admin list.
- Do not preserve old UX/config flows merely for compatibility. The Web Agent
  Console is the product direction.
- Allow schema changes when they improve the agent runtime, but keep existing
  local data through additive migrations where practical.
- Use source policy and deterministic hooks for access/copyright/rate-limit
  enforcement. Do not ask the LLM to decide whether a policy can be bypassed.

## Next Milestone: Step-Level Runtime Tasks

The next major development target is to persist the current internal crawl
pipeline steps as explicit DB task types:

```text
fetch_url -> parse_document -> extract_methods -> reconcile_candidate -> quality_check
```

Detailed work:

1. Add stable task-type constants for `fetch_url`, `parse_document`,
   `extract_methods`, `reconcile_candidate`, `quality_check`, and
   `review_action`.
2. Add payload contracts for each task type:
   - `fetch_url`: URL, source site id, policy settings.
   - `parse_document`: source document id, raw path, content type.
   - `extract_methods`: source document id, text path, extractor mode, target
     textbook scope.
   - `reconcile_candidate`: candidate id and retrieval context.
   - `quality_check`: job/session id and stop-condition context.
3. Update `CrawlTaskExecutor` to dispatch by explicit task type.
4. Keep `crawl_url` as a compatibility wrapper that creates or runs the step
   tasks until the UI/CLI fully switch over.
5. Store step observations in `crawl_tasks.result_json` with stable metrics and
   artifact ids.
6. Add retries/resume tests for each step, especially fetch success followed by
   extraction failure.
7. Update the crawl-job detail page so each URL shows a step timeline instead of
   one opaque `crawl_url` row.

## Quality and Stop Conditions

The runtime needs measurable stop rules so the agent does not crawl forever or
optimize the wrong thing.

Detailed work:

1. Define a `quality_snapshots` write path if the table is present, or add the
   table if it is still only documented.
2. Track per-job metrics:
   - fetched pages
   - failed/blocked pages
   - selected links
   - extracted candidates
   - created methods
   - created variants
   - duplicate/skip rate
   - pending review count
   - source yield per domain
3. Add `quality_check` tasks after every batch or after a configured interval.
4. Implement stop conditions such as:
   - no new methods after N pages
   - too many login-blocked pages from one source
   - source yield below threshold
   - review backlog above threshold
   - budget exhausted
5. Let `ExecutionMonitorAgent` propose strategy changes, but keep final task/job
   status derived from deterministic task counts.

## Review and Editing

The review system needs to move from status buttons to real curation tools.

Detailed work:

1. Add review item detail pages with source document, evidence snippets,
   candidate payload, matched canonical records, and AI rationale.
2. Add edit forms for candidate-derived method fields before approval.
3. Add canonical method and variant detail/edit pages.
4. Add mapping edit UI for section and knowledge-point links.
5. Add human-lock fields or policy so approved curated records cannot be
   overwritten automatically.
6. Add merge/split workflows only after basic edit and lock behavior is stable.
7. Make every review/edit path call `ReviewService` or a sibling runtime service
   instead of writing directly in routes.

## Source Access and Browser Fetching

HTTP fetching is enough for public pages. Login-gated or JavaScript-heavy pages
need an explicit, user-authorized browser path.

Detailed work:

1. Add source-level cookie profile metadata.
2. Add a Playwright-based fetcher for user-authorized domains.
3. Store browser storage state under `.data/cookies` or a configured secure
   location.
4. Scope cookie profiles by domain and expiration.
5. Never bypass captchas, paywalls, DRM, or cross-domain access restrictions.
6. Add review items when a source needs user action.
7. Add UI for blocked-login source status and cookie-profile refresh.

## Retrieval and Reconciliation

Current reconciliation is still shallow. The agent needs richer candidate
matching before automatic updates become trustworthy.

Detailed work:

1. Add a retrieval interface that can use SQL first and pgvector later.
2. Generate embeddings for teaching methods, variants, evidence snippets, and
   candidate payloads when AI configuration allows it.
3. Retrieve likely matches by textbook scope, title aliases, method steps, and
   semantic similarity.
4. Expand `ReconciliationAgent` input with retrieved matches and manual edit
   history.
5. Keep low-risk skip/update decisions auditable.
6. Route ambiguous matches, conflicts, and destructive changes to review.

## Worker Model

The current Web polling-driven due-job tick is acceptable for local first use.
It is not the final worker model.

Detailed work:

1. Keep the current due tick while the runtime contracts are still changing.
2. Add an independent worker command or process once step-level task contracts
   stabilize.
3. Use DB locking/claiming before adding concurrency.
4. Add per-domain concurrency limits.
5. Consider Celery, APScheduler, or a custom worker loop only after task payload
   and observation contracts are stable.

## Documentation Map

- `architecture.md`: product and system architecture.
- `agent-runtime.md`: runtime contract for agents, tools, observations, hooks,
  tasks, and review.
- `development-status.md`: current implemented/not-implemented state.
- `first-version-pipeline.md`: what the runnable first version does.
- `ai-control-plane.md`: human-Agent interaction and control-plane behavior.
- `data-model.md`: schema intent and table responsibilities.
- `crawl-policy.md`: crawl/access/copyright policy and runtime enforcement.
- `local-config.md`: local `.env`, AI provider, SQLite, and admin run notes.
- `source-notes.md`: initial source strategy notes.
