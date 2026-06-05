# 抽取 Prompt 设计

Last updated: 2026-06-05.

Runtime context: extraction prompts are tool prompts, not orchestration prompts.
They must return schema-constrained candidates only. Canonical writes still go
through runtime task observations, reconciliation decisions, and review/edit
services. See `docs/agent-runtime.md` and `docs/development-roadmap.md`.

MathScout 的 LLM 抽取必须使用受 schema 约束的 JSON 输出。模型不能输出自由散文，也不能编造输入文本中没有证据支持的教材版本、地区、章节、教师或方法。

## 教师方法抽取

### 输入

- 来源 URL 和来源元数据
- 解析后的网页/PDF 文本片段
- 可选的教材章节候选
- 已知学生能力编码表

### 输出

顶层必须是：

```json
{"methods": []}
```

每个 `methods` 元素包含：

- `title`
- `method_type`: `解题技巧`、`教学方法`、`易错提醒`、`建模套路`、`几何辅助线`、`计算策略`、`复习策略`
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
- `evidence_snippet`
- `confidence`

### 抽取规则

- 只抽取有教师方法价值的内容：解题路径、教学讲法、易错提醒、分类规则、辅助线策略、数形结合、建模思路、课堂任务设计等。
- 不要把普通目录、导航、教材知识点列表、广告、版权声明、下载按钮当作方法。
- 优先用自己的话概括，避免长段复制原文。
- `evidence_snippet` 必须短，只保留能支撑该方法的关键证据。
- 教材章节、地区、教师、学校必须由文本明确支持；如果只是推断，字段设为 `null` 或降低 `confidence`。
- 不要因为多个方法出现在同一篇文章中就强行合并。
- 当同一知识点出现不同教师讲法、不同辅助线、不同分类规则、不同直观模型或不同易错提醒时，要保留为不同方法或后续变体。
- 尽量映射到最具体的教材小节和知识点；无法确定时保留空值，不要硬填。

## 调和决策

### 输入

- 一个新候选知识项
- SQL/向量检索返回的相似 canonical 记录
- 候选证据片段
- 已有主知识库记录的证据摘要

### 输出

- `action`: `skip`、`update`、`create_variant`、`create`、`conflict`、`review`
- `matched_records`
- `rationale`
- `proposed_patch`
- `confidence`
- `requires_human_review`

### 决策规则

- `skip`: 候选没有新增概念、方法、章节映射、证据或教师变体，只更新来源计数和最后出现时间。
- `update`: 候选与已有主知识库记录相同，但提供了更强证据、更好表述、别名、步骤、易错点或适用题型。
- `create_variant`: 候选与已有主知识库教学方法同源同义，但教师讲法、辅助线、分类规则、直观模型、课堂提醒或题型模式有明显差异，值得保留。
- `create`: 在同一课程语境下没有已有记录表达同一含义。
- `conflict`: 候选与已有教材版本、章节归属、方法适用范围或地区采用证据冲突。
- `review`: 相似但不够确定，或置信度不足，必须进入人工复核。

所有调和理由必须引用来源证据，并说明不确定性。
