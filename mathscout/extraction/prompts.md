# Extraction Prompt Sketch

Use schema-constrained JSON output. The extractor must not invent textbook
versions, regions, chapters, or methods that are not supported by the input text.

## Teaching Method Extraction

Input:

- source metadata
- parsed text chunk
- nearby chapter/section candidates
- known skill catalog

Output:

- `title`
- `method_type`: 解题技巧, 教学方法, 易错点, 建模套路, 几何辅助线, 计算策略, 复习策略
- `source_teacher`
- `source_org`
- `source_region`
- `explanation_style`
- `summary`
- `steps`
- `applicable_patterns`
- `prerequisites`
- `common_misconceptions`
- `classroom_warnings`
- `example_patterns`
- `textbook_series`
- `book_code`
- `chapter_title`
- `section_title`
- `knowledge_point_titles`
- `skill_codes`
- `course_alignment_confidence`
- `evidence`
- `confidence`

Rules:

- Prefer paraphrase over copying source text.
- Keep evidence snippets short.
- Mark low confidence when textbook alignment is inferred.
- Do not merge different methods just because they appear in the same article.
- Preserve teacher-specific variants when a source has a distinct explanation,
  auxiliary construction, classification rule, mental model, warning, or problem pattern.
- Map every method to the most specific textbook section and knowledge point
  supported by evidence; mark low alignment confidence when the mapping is inferred.

## Reconciliation Decision

Input:

- one candidate knowledge item
- top retrieved canonical records from SQL/vector search
- candidate evidence snippets
- existing canonical evidence summary

Output:

- `action`: `skip`, `update`, `create_variant`, `create`, `conflict`, or `review`
- `matched_records`
- `rationale`
- `proposed_patch`
- `confidence`
- `requires_human_review`

Decision rules:

- Use `skip` only when the candidate adds no meaningful new concept, method,
  chapter mapping, or evidence beyond a source sighting.
- Use `update` when it is the same canonical item but the candidate adds stronger
  evidence, better wording, aliases, steps, misconceptions, or applicable patterns.
- Use `create_variant` when it is the same canonical teaching method but a teacher
  gives a meaningfully different classroom approach worth preserving.
- Use `create` when no existing item has the same meaning in the same curriculum
  context.
- Use `conflict` when the candidate contradicts existing version, chapter,
  method scope, or regional adoption evidence.
- Use `review` when similarity is plausible but not decisive.
- Always explain the decision with source-backed evidence and mention uncertainty.
