# Data Model

Last updated: 2026-06-05.

For the detailed implementation plan, see
[Development Roadmap](development-roadmap.md).

This document summarizes the normalized schema. SQLAlchemy models live in
`mathscout/db/models.py`.

## Canonical Education Tables

- `textbook_series`
  - publisher/version family
  - school system such as 六三制 or 五四制
  - curriculum standard basis
- `books`
  - grade, semester, edition label
  - maps to template ids such as `G7A`
- `chapters`
  - maps to ids such as `G7A-C1`
- `sections`
  - maps to ids such as `G7A-C1-S1`
- `student_skills`
  - global catalog such as S01-S16
- `knowledge_points`
  - canonical knowledge point records
- `teaching_methods`
  - first-class canonical problem-solving techniques
  - stores shared method identity, method type, summary, common steps, applicable task patterns, prerequisites, and source count
- `teaching_method_variants`
  - source-specific teacher versions of a canonical technique
  - preserves different classroom explanations, step orders, intuitions, warnings, and examples
- `method_section_links`
  - maps techniques to textbook sections, with relation type and confidence
- `method_knowledge_point_links`
  - maps techniques to knowledge points, with relation type and confidence
- `region_adoptions`
  - evidence-backed textbook usage by region/school

## Provenance Tables

- `source_sites`
- `source_documents`
- `evidence_snippets`
- `extraction_runs`
- `review_items`
- `manual_edit_logs`
  - audit trail for every human edit
  - stores table name, target id, action type, before payload, after payload, reason, editor, and rollback metadata

## Candidate and Reconciliation Tables

- `candidate_knowledge_items`
  - one structured candidate extracted from one source document or chunk
  - stores item type, normalized payload, evidence, confidence, and extraction run
  - candidates are immutable; corrections create new candidates or review edits
- `reconciliation_decisions`
  - AI decision for a candidate: `skip`, `update`, `create_variant`, `create`, `conflict`, or `review`
  - stores matched canonical ids, rationale, confidence, and proposed database patch
  - provides the audit log for why the knowledge base changed or did not change

## AI Orchestration Tables

- `orchestration_sessions`
  - one AI-managed work session created from a human goal
  - stores current objective, target scope, budget, status, active strategy, and stop conditions
- `natural_language_commands`
  - user instructions entered in the admin command center
  - stores raw command text, AI interpretation, structured directive, and execution status
- `agent_decisions`
  - audit log for AI decisions such as creating tasks, changing source priority,
    pausing a source, retrying a failed task, applying a reconciliation result, or stopping a session
  - every decision should include rationale, input metrics, policy checks, and confidence
- `quality_snapshots`
  - periodic metrics used by the AI orchestrator
  - includes chapter coverage, source yield, duplicate rate, conflict rate, average confidence,
    login-blocked count, failure count, budget usage, and novelty trend
  - currently planned/documented; implement the write path when `quality_check`
    tasks are added

## Manual Editing Rules

- human edits are first-class data, not comments outside the system
- canonical knowledge points, teaching methods, variants, and mappings can be edited in the admin UI
- edited records can be marked as human-locked so AI cannot overwrite them automatically
- AI may still propose updates to human-locked records, but those proposals must enter review
- merges, splits, deletes, and mapping changes should always write `manual_edit_logs`
- review approvals should also write edit logs when they modify canonical data

## Job Tables

- `crawl_jobs`
  - DB-backed queue group created from a human goal, CLI command, or future
    scheduled job
  - stores source filter, extractor mode, strategy settings, and status
- `crawl_tasks`
  - DB-backed queue item
  - current wired task types: `discover_links`, `crawl_url`
  - next explicit task types: `fetch_url`, `parse_document`, `extract_methods`,
    `reconcile_candidate`, `quality_check`, `review_action`
  - `result_json` stores a normalized runtime observation with status,
    artifact ids, metrics, warnings, retryability, review flags, and payload
  - `not_before` stores delayed execution time for crawl-delay enforcement

Current migration behavior:

- `mathscout/db/migrations.py` contains lightweight additive schema checks for
  the current local-first runtime.
- App startup and `mathscout init-db` call `ensure_database_schema()`.
- Alembic is still the target for serious PostgreSQL migrations, but current
  local SQLite schema evolution should remain additive and non-destructive.

## Important Relationships

- one textbook series has many books
- one book has many chapters
- one chapter has many sections
- one section has many knowledge points
- teaching methods can link to multiple sections and knowledge points
- one canonical teaching method can have many teacher/source variants
- method reconciliation should preserve meaningful variants instead of over-merging
- every extracted record should link to at least one evidence snippet when possible
- region adoption records must link to evidence, not just free text
- crawled extraction output should not write directly into canonical tables
- new extraction output first becomes a candidate, then the reconciliation agent
  decides whether to skip, update, create, mark conflict, or request review
- canonical records should track repeated sightings through evidence/source counts,
  while candidate records preserve the exact source-backed extraction result
- humans should mostly interact with `natural_language_commands`, dashboards, and
  review queues; the AI orchestrator translates direction into structured plans
- AI execution must be auditable through `agent_decisions` and measurable through
  `quality_snapshots`
- human changes must be auditable through `manual_edit_logs`; AI reconciliation
  should use those logs when deciding whether to skip, update, or request review

## Schema Work Still Needed

- Persist step-level task payloads for fetch, parse, extract, reconcile, and
  quality check.
- Add or finalize `quality_snapshots` if it is absent from the SQLAlchemy
  models.
- Add human-lock metadata for curated canonical records.
- Add cookie-profile metadata for user-authorized login sources.
- Add embedding/vector metadata for retrieval once pgvector or another vector
  store is chosen.
- Add a real message/thread table only if Agent Console multi-turn memory
  requires more than `natural_language_commands`, `orchestration_sessions`,
  `agent_decisions`, and `crawl_jobs`.
