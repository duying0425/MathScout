# MathScout Architecture

Last updated: 2026-06-05.

This is the concise architecture reference. Use
[Development Roadmap](development-roadmap.md) for current baseline and next
work, [Agent Runtime](agent-runtime.md) for execution contracts, and
[Data Model](data-model.md) for schema responsibilities.

## Product Shape

MathScout is a supervised AI agent system for maintaining a junior-middle-school
math teaching-method knowledge base.

The crawler is an input tool, not the product. The product value is:

- collecting teacher problem-solving techniques
- preserving meaningful teacher/source variants
- mapping methods to textbook sections and knowledge points
- keeping source provenance and short evidence snippets
- reconciling new candidates with existing canonical data
- routing uncertain or risky changes to human review

## Main Loop

```text
human goal in Web Agent Console
  -> command interpretation
  -> orchestration plan
  -> DB task creation
  -> deterministic tool execution
  -> structured observation
  -> extraction and reconciliation
  -> quality/stop decision
  -> review/edit when needed
  -> audited canonical update
```

The primary human interface is `/admin/agent`. The CLI is for setup, local smoke
tests, and emergency job control.

## Runtime Boundary

The current runtime is DB-backed:

- `crawl_jobs` groups work.
- `crawl_tasks` stores executable units and observations.
- `agent_decisions` records planning, strategy, monitor, and review decisions.
- `review_items` and `manual_edit_logs` make human review part of the runtime.

Current wired task types are `discover_links` and `crawl_url`. `crawl_url` is a
compatibility wrapper; internally it delegates to:

```text
fetch_url -> parse_document -> extract_methods -> reconcile_candidate
```

The next architecture step is to persist those internal steps as explicit task
types, then add `quality_check` and `review_action`.

## Agent and Tool Roles

Agents decide. Tools execute.

- `NaturalLanguageCommandAgent`: converts human goals into structured
  directives.
- `AIOrchestratorAgent`: plans work and strategy.
- `SourceDiscoveryAgent`: selects child links from fetched seed-page candidates.
- `ExecutionMonitorAgent`: proposes continue, pause, stop, review, or strategy
  changes.
- Extractors create schema-constrained candidates.
- Reconciliation compares candidates with canonical data and proposes skip,
  update, create, create_variant, conflict, or review.

Deterministic tools enforce hard constraints:

- URL validity
- source enabled/access policy
- robots.txt
- crawl delay through `crawl_tasks.not_before`
- HTTP failure handling
- login-gate detection
- unsupported content checks
- empty/boilerplate page checks
- review and audit writes

## Data Layers

- Canonical layer: textbook structure, knowledge points, teaching methods,
  method variants, mappings, and regional adoption.
- Provenance layer: source sites, source documents, evidence snippets, raw/text
  file paths.
- Candidate layer: extraction runs, candidate knowledge items, reconciliation
  decisions.
- Runtime layer: commands, sessions, decisions, crawl jobs, crawl tasks,
  observations, review items, manual edit logs.

## Worker Model

Current local runtime uses Web status polling to trigger due pending jobs. This
is acceptable while task contracts are still changing.

Add an independent worker only after step-level task payloads and observations
are stable. At that point implement DB task claiming, per-domain concurrency,
clean shutdown/resume behavior, and then choose the simplest worker
implementation that fits the queue behavior.

## Guardrails

MathScout must not bypass captchas, paywalls, DRM, robots policy, disabled
sources, or cross-domain cookie boundaries. Login-gated sources require
user-authorized cookie profiles and review. Public but commercial/full-text
copyrighted resources should be reviewed before extracted summaries affect
canonical data.
