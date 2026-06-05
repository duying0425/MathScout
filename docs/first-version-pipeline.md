# First Version Pipeline

Last updated: 2026-06-05.

For the detailed roadmap beyond the first runnable version, see
[Development Roadmap](development-roadmap.md).

The first implementation is intentionally small and runnable. It proves the
database update loop and now includes an LLM-first multi-agent control plane with
deterministic fallbacks for local/offline runs.

## Commands

The primary product-facing flow is the Web Agent Console:

```text
http://127.0.0.1:8000/admin/agent
```

Users can type a goal such as:

```text
请帮我抓取http://www.example.com/test下的数据，优先提取初中数学教师解题方法。
```

The CLI remains useful for setup, smoke tests, and emergency control:

```powershell
mathscout init-db
mathscout import-template
mathscout seed-sources
mathscout crawl-url "https://example.com/public-math-teaching-page" --extractor auto
mathscout create-job --name "batch" --url "https://example.com/a" --url "https://example.com/b"
mathscout run-job "<job_id>" --extractor auto
mathscout stop-job "<job_id>"
```

## What It Does

1. Creates database tables from SQLAlchemy metadata.
2. Imports `.template` textbook structure:
   - textbook series
   - books
   - chapters
   - sections
   - knowledge points
   - shared student skills
3. Registers default source sites.
4. Fetches one URL with `HttpFetcher`.
5. Parses HTML or PDF to text.
6. Stores source metadata in `source_documents`.
7. Stores short evidence snippets.
8. Runs `AIMethodExtractor` when DeepSeek/OpenAI-compatible config is present;
   otherwise falls back to `RuleBasedMethodExtractor`.
9. Lets `NaturalLanguageCommandAgent`, `AIOrchestratorAgent`, `SourceSelectionAgent`,
   `ExecutionMonitorAgent`, and `ReconciliationAgent` drive command interpretation,
   planning, link selection, execution decisions, and candidate reconciliation when AI is enabled.
10. Stores extracted method candidates in `candidate_knowledge_items`.
11. Creates or updates:
    - `teaching_methods`
    - `teaching_method_variants`
    - `reconciliation_decisions`
12. If candidate text contains an existing knowledge point title, it creates:
    - `method_knowledge_point_links`
    - `method_section_links`
13. Runs deterministic runtime hooks for URL validity, source access policy,
    robots, crawl delay, HTTP failures, login gates, unsupported content, empty
    pages, and boilerplate pages.
14. Stores normalized runtime observations in `crawl_tasks.result_json`.
15. Routes review actions through `ReviewService` and writes `manual_edit_logs`.

`CrawlPipeline.crawl_url()` remains the compatibility wrapper, but internally it
now delegates to `fetch_url`, `parse_document`, `extract_methods`, and
`reconcile_candidate` methods.

## Current Limits

- AI extraction uses an OpenAI-compatible `/chat/completions` endpoint, currently
  configured for DeepSeek by default.
- If AI is unavailable in `auto` mode, extraction falls back to rule-based keyword detection.
- If AI is unavailable for the control plane, command interpretation, planning,
  source selection, execution monitoring, and reconciliation fall back to local deterministic behavior.
- Course mapping only uses simple knowledge-point title matching.
- Crawling can run as a persistent DB-backed job, but it still processes URLs sequentially.
- Robots and per-domain crawl delay are wired into the DB-backed job runtime.
  Crawl delay defers tasks through `crawl_tasks.not_before` rather than sleeping
  inside the worker.
- Due pending jobs currently resume through Web status polling; there is not yet
  an independent always-on worker process.
- Admin viewing pages are database-backed, but edit workflows are still incomplete.
- Fetch, parse, extract, and reconcile are internal method boundaries, not yet
  persisted as separate DB task types.

## Next Step

Persist fetch/parse/extract/reconcile as explicit DB task types, then add
quality-check tasks, source-yield metrics, review detail/edit pages,
Playwright/cookie-profile fetching, and retrieval/vector search.
