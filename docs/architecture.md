# MathScout Architecture

## 1. Product Scope

MathScout should become an AI-managed knowledge-base maintenance system, not
just a scraper. Crawling is only the input layer. The primary product function is
that backend AI agents plan, schedule, execute, monitor, and reconcile knowledge
work. Human users supervise through dashboards and natural-language instructions:
they set direction, inspect quality, approve risky changes, and correct strategy.

The most valuable output is a maintained teacher problem-solving technique
library. Knowledge points and textbook structure provide the indexing framework,
but the app should optimize for collecting, preserving, and organizing diverse
teacher know-how.

The canonical knowledge graph should contain:

- textbook version, school system, edition label, and regional adoption evidence
- book, chapter, section, and cross-semester dependency graph
- teaching methods, problem-solving know-how, common misconceptions, and example-task patterns
- technique variants from different teachers or sources
- knowledge points from curriculum standards, textbook directories, teacher guides, and lesson plans
- student skills such as number sense, model building, geometric intuition, proof, classification, and validation
- provenance for every extracted claim

The `.template` folder already gives a good first normalized hierarchy:

```text
TextbookSeries -> Book/Semester -> Chapter -> Section
Section -> KnowledgePoint
Section -> StudentSkill refs
Chapter/Section -> CrossSemesterLink
```

MathScout extends that into a source-backed database by adding documents,
evidence snippets, candidate records, reconciliation decisions, extraction runs,
and review status.

### Problem-Solving Techniques Are First-Class

The app should not flatten different teachers' approaches into a single bland
summary. A canonical technique should represent the shared method, while variants
preserve useful differences:

- teacher wording or teaching sequence
- alternative entry point or intuition
- different auxiliary line, model, or transformation path
- different applicable problem pattern
- common misconception or classroom warning
- source teacher, school, region, and document provenance when available

For example, two teachers may both teach "数形结合比较有理数大小", but one uses
number-line distance intuition and another uses sign/absolute-value classification.
Those should map to the same section and possibly the same canonical technique,
but remain separate variants if their classroom method is meaningfully different.

## 2. Operating Model

MathScout runs in an AI-led orchestration mode:

```text
Human natural-language goal
  -> AI Orchestrator interprets target, scope, budget, and quality bar
  -> Policy Guard checks hard constraints
  -> AI Orchestrator creates crawl/extract/reconcile tasks
  -> Worker agents execute tasks
  -> Quality Monitor reports coverage, novelty, conflicts, and failure modes
  -> AI Orchestrator adjusts strategy or decides to stop
  -> Human monitors, redirects, approves, or pauses through the admin UI
```

The AI can actively manage:

- crawl target selection and crawl priority
- per-source exploration depth within configured limits
- worker task allocation
- extraction and reconciliation sequencing
- quality monitoring and coverage-gap detection
- retry, pause, resume, and stop decisions
- strategy changes based on duplicate rate, source quality, conflicts, and budget

The system still enforces hard guardrails with deterministic code:

- no captcha, paywall, or DRM bypass
- no cross-domain cookie reuse
- no ignoring disabled domains, rate limits, or crawl budgets
- no destructive deletion without explicit human approval
- no publishing high-risk conflicts without review
- no storing or republishing full copyrighted resources as canonical output

## 3. Source Strategy

Use a tiered source policy.

### Tier 1: Official Baseline

- Ministry of Education curriculum standards.
- Ministry of Education teaching-book catalogs.
- National Smart Education Platform public metadata and public course resources.
- Provincial, city, and district education bureau teaching-book selection or ordering notices.

These sources define the canonical baseline. They should be crawled first and used
to validate textbook editions and regional adoption.

### Tier 2: Publisher and Textbook Companion Sources

- Publisher pages for 人教版, 北师大版, 华东师大版, 北京版, 湘教版, 冀教版, 鲁教版, 苏科版, 沪科版, 浙教版, 青岛版, etc.
- Public textbook catalogue pages, errata, training notices, teacher training slides, and sample resources.

These sources are useful for version metadata and chapter structure, but should be
kept separate from regional adoption evidence.

### Tier 3: Public Teacher Resources

- Public lesson plans, micro-lessons, teaching reflections, open class records, public worksheets, and teaching-research articles.
- Public content from education bureau teaching-research sites and school sites.

This tier is where most know-how comes from. The app should store short evidence
snippets and structured summaries, not blindly republish full copyrighted documents.

### Tier 4: Login-Gated Sources

Login-gated sources can be supported only when the user has permission to access
them. MathScout should detect login walls, mark the source as `login_required`,
and wait for a user-provided browser cookie profile or Playwright storage state.
It should not bypass captchas, paywalls, or access controls.

## 4. Data Model

Core tables:

- `source_sites`: domain-level source configuration, access policy, crawl priority, rate limits.
- `source_documents`: one URL/PDF/video/page, fetch status, checksums, raw file path, extracted text path.
- `evidence_snippets`: short source-backed spans used to justify extracted claims.
- `textbook_series`: publisher/version family, e.g. 北师大版初中数学（六三制）.
- `books`: grade and semester books, e.g. G7A 七年级上册.
- `chapters` and `sections`: textbook structure.
- `knowledge_points`: normalized concepts aligned to sections.
- `student_skills`: global skill catalog, initially compatible with S01-S16 from `.template`.
- `teaching_methods`: problem-solving techniques, teaching methods, misconceptions, and patterns.
- `teaching_method_variants`: source-specific teacher approaches linked to a canonical method.
- `method_section_links`: maps techniques to textbook sections.
- `method_knowledge_point_links`: maps techniques to knowledge points.
- `region_adoptions`: province/city/district/school adoption records with evidence and confidence.
- `candidate_knowledge_items`: structured records extracted from one newly parsed document.
- `reconciliation_decisions`: AI decisions to skip, update, create, mark conflict, or require review.
- `orchestration_sessions`: AI-managed work sessions created from human goals.
- `natural_language_commands`: user instructions, AI interpretation, and resulting plan.
- `agent_decisions`: audit log for AI scheduling, strategy, retry, stop, and quality decisions.
- `quality_snapshots`: coverage, duplicate rate, conflict rate, extraction confidence, and source quality metrics.
- `manual_edit_logs`: human edits to canonical knowledge, teaching methods, variants, links, and source metadata.
- `crawl_jobs` and `crawl_tasks`: orchestration and retry tracking.
- `extraction_runs`: model, prompt version, input document, output hash, and review status.
- `review_items`: queue for human validation.

Every generated knowledge record should have:

- source document id
- evidence snippet id where possible
- extractor version
- confidence
- review status
- conflict markers when sources disagree
- manual edit status and lock fields when a human has curated the record

## 5. Pipeline

```text
Human Goal / Natural Language Command
  -> AI Orchestrator
  -> Policy Guard
  -> Source Discovery / Task Planning
  -> Crawl Agents
  -> Parse Agents
  -> Extraction Agents
  -> Candidate Knowledge Items
  -> Retrieval Against Existing DB
  -> Reconciliation Agent
  -> Decision: skip | update | create | conflict | review
  -> Quality Monitor
  -> AI Strategy Adjustment / Stop Decision
  -> Human Dashboard and Review for risky decisions
  -> Publish to Canonical Knowledge Graph
```

### Fetchers

- `HttpFetcher`: static HTML, PDFs, known APIs, and simple downloads.
- `BrowserFetcher`: Playwright-based rendering for JavaScript-heavy or login-gated pages.
- `ManualUploadFetcher`: user-supplied PDF/DOC/PPT resources.

All fetchers should emit a `source_document` record and never directly create
canonical knowledge records.

### Parsers

- HTML: trafilatura first, BeautifulSoup fallback.
- PDF: PyMuPDF text extraction, OCR fallback later.
- DOCX/PPTX: add later if needed.
- Video: store metadata first; transcript extraction only when captions or legal transcription is available.

### Extractors

Use schema-constrained extraction. Do not ask an LLM for free-form blobs.
Each extractor returns JSON matching one schema:

- `TextbookStructureExtraction`
- `KnowledgePointExtraction`
- `TeachingMethodExtraction`
- `RegionAdoptionExtraction`
- `SkillMappingExtraction`

Extractor output is not immediately canonical. It first becomes a candidate item.

For teaching-method extraction, the agent should capture:

- method title and type
- teacher/source name when available
- textbook series, book, chapter, section, and knowledge point alignment
- applicable problem pattern
- step-by-step solution path
- why this method works
- when not to use it
- common mistakes it prevents
- prerequisite skills
- evidence snippets

### Reconciliation Agent

The reconciliation agent is the core backend agent. For every candidate item it:

1. Builds a semantic search query from title, aliases, chapter alignment, skill refs,
   method steps, and evidence snippets.
2. Retrieves likely existing records from `knowledge_points`, `teaching_methods`,
   `student_skills`, and regional adoption tables.
3. Compares the candidate against existing records on:
   - textbook version, book, chapter, and section
   - concept meaning and aliases
   - method steps and applicable problem patterns
   - evidence source authority and freshness
   - confidence and review status
4. Emits one explicit decision:
   - `skip`: duplicate or weaker evidence; only update `last_seen_at` and source count.
   - `update`: same canonical item with better wording, stronger evidence, or new applicable patterns.
   - `create_variant`: same canonical method, but a meaningfully different teacher approach worth preserving.
   - `create`: genuinely new knowledge point, method, skill, or regional adoption record.
   - `conflict`: source disagrees with existing canonical data.
   - `review`: ambiguous match or low confidence.
5. Writes a `reconciliation_decision` record with rationale, candidate id, matched
   canonical ids, confidence, and proposed patch.

Only low-risk `skip` decisions should be fully automatic. For teaching methods,
`create_variant` is preferred over aggressive merging when a source adds a real
teaching difference. `update`, `create`, and `create_variant` can be auto-applied
only after confidence thresholds are proven with review data. `conflict` always
enters the review queue.

### AI Orchestrator

The AI Orchestrator is the main runtime manager. It receives human goals such as:

```text
优先把北师大版七年级上册公开资料抓完，重点补充有理数和一元一次方程的教师解题方法。
如果连续 50 篇资料没有新增方法，就暂停该来源并换省级教研站点。
```

It translates that into structured plans:

- target textbook series, books, chapters, and sections
- source tiers and domains to use
- crawl depth, batch size, and budget
- quality targets such as coverage and minimum evidence count
- stop conditions
- review thresholds

Every orchestrator decision is written to the audit log. The UI should show what
the AI decided, why it decided that, what it will do next, and which rule or user
instruction authorized it.

### Manual Review and Editing

The admin UI must support direct human correction. AI can manage the pipeline,
but human curation is part of the data model.

Manual edit capabilities:

- view textbook tree, knowledge points, canonical techniques, and teacher variants
- edit technique title, type, summary, steps, applicable patterns, prerequisites, and warnings
- edit a technique's knowledge-point and section mappings
- merge duplicate techniques or split one over-merged technique into separate records
- approve, reject, or rewrite AI reconciliation proposals
- lock curated records so future AI runs cannot overwrite them automatically
- inspect source evidence before accepting an AI-created method or variant
- view change history and compare before/after payloads

AI behavior after manual edits:

- human-locked records can only receive AI proposals, not direct AI updates
- AI should treat human-approved wording and mappings as higher-authority data
- future reconciliation should cite manual edit history when proposing changes
- destructive edits, merges, and splits require explicit human action

## 6. Agent Design

The "subagent" idea maps cleanly to queue workers. Each agent is a focused worker
that reads tasks, writes structured outputs, and records confidence.

- `AIOrchestratorAgent`: owns the active goal, creates tasks, changes priorities, and decides continue/pause/stop.
- `NaturalLanguageCommandAgent`: converts user instructions into structured directives.
- `PolicyGuardAgent`: blocks actions that violate access, copyright, budget, or destructive-change rules.
- `SourceDiscoveryAgent`: discovers candidate official and public sources.
- `LoginGateAgent`: detects login/captcha/paywall states and asks for cookie input.
- `CrawlAgent`: fetches source documents with per-domain rate limits.
- `ParseAgent`: converts raw pages/PDFs to text and layout-aware chunks.
- `CurriculumMapperAgent`: aligns text to book/chapter/section.
- `KnowledgeAgent`: extracts knowledge points and prerequisite relationships.
- `MethodAgent`: primary extraction agent; extracts teacher problem-solving techniques, variants, misconceptions, and applicable task patterns.
- `CourseMappingAgent`: maps each technique to textbook version, chapter, section, knowledge point, and student skill.
- `RegionAdoptionAgent`: extracts regional textbook usage from education-bureau notices.
- `RetrievalAgent`: retrieves candidate matches from existing canonical tables and vector indexes.
- `ReconciliationAgent`: decides skip/update/create/conflict/review and proposes database patches.
- `DedupValidateAgent`: validates reconciliation decisions, merges duplicates, flags conflicts, and assigns review priority.
- `QualityMonitorAgent`: measures coverage, duplicate rate, conflict rate, source usefulness, and extraction confidence.
- `StopConditionAgent`: recommends stop/pause/continue based on configured goals and quality metrics.

Implementation detail: start with Celery tasks. If later we need more explicit
agent state, introduce LangGraph or a custom state machine behind the same task
interfaces.

## 7. Login and Cookie Flow

1. Fetcher receives 401/403, login redirect, captcha marker, or empty protected page.
2. Create a `review_item` with type `login_required`.
3. Admin UI shows the source URL and domain.
4. User logs in manually in a browser.
5. User exports Playwright storage state or pastes cookies for that domain.
6. MathScout stores the cookie profile encrypted at rest.
7. Crawl job resumes with that cookie profile.

Cookie profiles should be scoped by domain and expiration. They should not be
shared across domains or exported in logs.

## 8. Admin UI

First admin views:

- Dashboard: source count, crawl jobs, fetched docs, extraction volume, review queue.
- AI Command Center: chat with the orchestrator, set goals, change scope, pause or resume work.
- AI Plan View: current goal, active plan, source priorities, budgets, stop conditions, and next actions.
- Sources: domain settings, access level, rate limits, robots status, enabled/disabled.
- Crawl Jobs: status, retries, errors, fetched documents.
- Documents: raw URL, parsed text preview, content hash, source type, login status.
- Review Queue: accept/reject/edit extracted knowledge and teaching methods.
- Reconciliation Queue: inspect candidate, matched existing records, AI rationale, and proposed patch.
- Knowledge Browser: filter by textbook version, grade, chapter, section, skill, method type.
- Technique Library: browse by textbook section, method type, teacher variant, task pattern, prerequisite skill, and evidence strength.
- Edit Forms: manually modify knowledge points, canonical techniques, variants, and course mappings.
- Change Log: audit human edits, AI decisions, before/after payloads, and rollback candidates.
- Region Map/Table: province/city/district adoption evidence and confidence.
- Quality Monitor: coverage by version/chapter, novelty rate, duplicate rate, source yield, conflicts, and low-confidence areas.

Keep the admin UI simple. Server-rendered FastAPI/Jinja pages are enough until
the data volume or review workflow demands a richer frontend.

## 9. Copyright and Compliance

The crawler should be conservative:

- respect robots.txt where applicable
- throttle per domain
- keep full raw documents private
- store source URLs and short evidence snippets for review
- summarize and transform teaching methods instead of republishing full resources
- do not bypass paywalls, captchas, DRM, or platform terms
- preserve attribution and provenance

This matters because textbook PDFs, teacher guides, and commercial teaching
resources are usually copyrighted even if they can be viewed online.

## 10. Development Roadmap

### Phase 0: Skeleton

- Project structure, config, database models, Docker Compose.
- Import `.template` JSON into canonical tables.

### Phase 1: Official Baseline

- Seed official source list.
- Crawl Ministry of Education catalog and curriculum standard PDFs.
- Crawl provincial/city teaching-book notices.
- Build regional adoption evidence table.
- Add AI command sessions and initial orchestrator planning.

### Phase 2: Public Resource Crawl

- Add public teacher-resource source registry.
- Crawl HTML/PDF resources with strict rate limits.
- Parse and chunk documents.

### Phase 3: Extraction and Review

- Implement JSON-schema extraction.
- Add candidate records, retrieval, reconciliation decisions, deduplication, and conflict detection.
- Build review UI.

### Phase 4: Scale

- Parallel workers per domain group.
- Vector search over methods and examples.
- Incremental recrawling and freshness checks.
- Quality reports by textbook version and chapter.
- AI-led adaptive strategy based on quality snapshots and human natural-language feedback.

## 11. Open Decisions

- Which textbook versions should be prioritized after 北师大版?
- Whether to store embeddings in the main PostgreSQL database via pgvector or in a separate vector database.
- Whether authenticated sources are for private research only or can contribute to shared published summaries.
- Whether examples and problem statements should be stored verbatim, paraphrased, or only used as evidence for extracted methods.
- Which actions can be auto-applied by the AI in the early version, and which must remain review-only until enough audit data exists.
