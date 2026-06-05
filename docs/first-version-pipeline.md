# First Version Pipeline

The first implementation is intentionally small and runnable. It proves the
database update loop and now includes an LLM-first multi-agent control plane with
deterministic fallbacks for local/offline runs.

## Commands

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

## Current Limits

- AI extraction uses an OpenAI-compatible `/chat/completions` endpoint, currently
  configured for DeepSeek by default.
- If AI is unavailable in `auto` mode, extraction falls back to rule-based keyword detection.
- If AI is unavailable for the control plane, command interpretation, planning,
  source selection, execution monitoring, and reconciliation fall back to local deterministic behavior.
- Course mapping only uses simple knowledge-point title matching.
- Crawling can run as a persistent DB-backed job, but it still processes URLs sequentially.
- Robots and per-domain scheduling are designed but not yet wired into the CLI pipeline.
- Admin viewing pages are database-backed, but edit workflows are still incomplete.

## Next Step

Add retrieval/vector search and manual review/edit workflows so the AI agents can
compare candidates against richer context and route risky decisions to humans.
