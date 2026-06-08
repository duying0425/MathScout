# 知识图谱重构：四维模型（Knowledge Graph Redesign）

> 状态：**设计已定稿，开发待启动**。本文是这次重构的**单一事实来源**与开发指南，
> 供新对话 / 其他开发者接手时对齐。实现进度请同步更新
> [development-status.md](development-status.md) 与 [architecture.md](architecture.md)
> 顶部的状态对照表。

## 1. 背景与动机

MathScout 首版只抓"教学方法"，并把知识点硬挂在单个教材小节下。重新梳理数据关系后，
确定把覆盖范围升级为**四个维度的知识图谱**：

| 维度 | 实体 | 与版本的关系 |
|------|------|--------------|
| 教材 / 章 / 节 | `textbook_series` → `books` → `chapters` → `sections` | **版本相关**：只决定讲课顺序与选材 |
| 知识点 | `knowledge_points` | **版本无关**：跨版本唯一、共享 |
| 题目 | `problems`（新增） | **版本无关**：弱关联到小节 |
| 解题技巧 / 模型 | `teaching_methods`（沿用） | **版本无关**：跨题复用（将军饮马、手拉手…） |

核心原则（这次重构的"宪法"）：

1. **教材是视图，不是事实。** 不同教材版本只影响章节顺序、选材深度与术语；它们都应
   映射到**同一套**知识点与题目。
2. **知识点与题目是稳定事实，必须 canonical（跨版本唯一）。** 同一个"求根公式"，
   人教版和北师大版必须是**同一条**记录，不能因为挂在不同小节而重复。
3. **题目考察的知识点是出题前设计好的**，因此 `problem ↔ knowledge_point` 是一条
   真实存在、可建模的"考察"关系。
4. **解答（Solution）≠ 解题技巧（Technique）。**
   - 解答：某道**具体题**的一条解题路径（题目专属，可一题多解）。
   - 技巧 / 模型：跨题复用的抽象方法（= 现有 `teaching_methods`）。
   - 关系是多对多：一条解答可用到 0 / 1 / 多个技巧；一个技巧被很多解答复用。
   - **不要**把每道题的解法都新建成一个"技巧"，否则会污染可复用技巧库。

> 术语对照：文档里说的"**解题技巧 / 模型 / Technique**"在数据库里就是现有的
> `teaching_methods` 表（不改表名，避免大范围重命名）。"**解答 / Solution**"是新增的
> 题目专属实体。

### 1.1 关键术语表（术语宪法）

> 这张表与上面的核心原则**同属"宪法"**：任何代码、注释、prompt、UI 文案、表/字段命名
> 出现理解分歧时，以本表为准。先看"消歧"列里的 ⚠ 项——它们是最容易搞混的点。

| 中文术语 | 英文 / 代码名 | 数据库对象 | 含义与消歧（⚠ = 易混点）|
|----------|---------------|------------|--------------------------|
| 视图 / 事实 | View / Fact | —（原则）| 教材是**视图**（只决定顺序与选材），知识点与题目是**事实**（跨版本稳定）。建模冲突先回到这条 |
| 教材系列 | Textbook Series | `textbook_series` | 版本族（人教版 / 北师大版…），**版本相关** |
| 册 / 章 / 节 | Book / Chapter / Section | `books` / `chapters` / `sections` | 教材结构，**版本相关**；是事实的"视图"，本身不承载唯一事实 |
| 知识点 | Knowledge Point (KP) | `knowledge_points` | **版本无关、canonical、跨版本唯一**的概念。⚠ 不等于"学生能力" |
| 学生能力 | Student Skill | `student_skills` | 横切能力标签（运算 / 几何直观 / 推理…），正交维度，**不属四维**。⚠ 别与知识点混 |
| 题目 | Problem | `problems` | **版本无关**、LaTeX 题干、可含答案；**弱关联**到小节 |
| 解答 | Solution | `solutions` | 某道题的**一条**解题路径，可**一题多解**。⚠ **解答 ≠ 技巧**：解答题目专属 |
| 解题技巧 / 模型 | Technique / Model | `teaching_methods` | **跨题复用**的抽象模型（将军饮马、手拉手）。⚠ 数据库表名仍是 `teaching_methods`，不改名 |
| 方法变体 | Method Variant | `teaching_method_variants` | 同一技巧的不同教师讲法 / 步骤顺序，保留有价值差异 |
| 配图 | Figure | `figures` | 题干 / 解步配图：原图 `image_path` + 可选 AI 生成 `tikz_code` |
| 覆盖（小节→知识点）| covers | `section_knowledge_point_links` | 替代旧 `section_id` 硬绑定；M:N，`relation_type`: introduce / reinforce / extend |
| 考察（题目→知识点）| tests / assesses | `problem_knowledge_point_links` | 出题前设计好的关系；AI 标注，⚠ **低置信、强制进复核**，不自动入库 |
| 弱关联（题目→小节）| weakly linked | `problem_section_links` | 题目从某小节"提起"但跨版本共通；⚠ **软链接、非归属** |
| 用到（解答→技巧）| uses | `solution_technique_links` | 一条解答用到 **0 / 1 / 多个**技巧；优先匹配已有技巧库，避免一题一技巧 |
| 语义键 | Semantic Key | `semantic_key` | 内容**去重键**。⚠ KP 要从"带 section 作用域"改为**基于内容**，否则跨版本去重失效 |
| 主记录 | Canonical | （各 canonical 表）| 跨来源 / 跨版本**唯一**的事实记录；与"候选 / 变体"相对 |
| 候选 | Candidate | `candidate_knowledge_items` | 单篇文档抽取出的**不可变**结果，**尚未入库** |
| 调和 | Reconciliation | `reconciliation_decisions` | 候选 → 主记录的决策：skip / update / create / create_variant / conflict / review |

## 2. 现状的结构矛盾（为什么必须改）

当前 [models.py](../mathscout/db/models.py) 把知识点绑死在单个小节：

```python
class KnowledgePoint(Base):
    section_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sections.id"), index=True)  # ← 硬绑定
```

且导入器 [template.py](../mathscout/importers/template.py) 生成的去重键**带 section 作用域**：

```python
semantic_key = normalize_semantic_key(f"{series.name}:{book.book_code}:{section.section_code}:{point}")
```

后果：同一个知识点出现在两个版本（或同版本两个小节）就会变成**两条记录**，直接违背
"跨版本一致"原则。这是本次重构**第一优先级**要修的结构性问题，且**不依赖抓题目**即可
独立完成、独立验证。

## 3. 目标数据模型

```
【版本视图层】影响顺序/选材，不代表事实
  textbook_series ─< books ─< chapters ─< sections
                                            │
       ┌────────────────────────────────────┼──────────────────────────────┐
       │ section_knowledge_point_links       │ problem_section_links         │
       │ (M:N) relation_type:                │ (M:N, 弱关联)                  │
       │   introduce/reinforce/extend        │ relation_type: exercise_of…    │
       ▼                                     ▼
【事实层】canonical，跨版本唯一
  knowledge_point ◄── problem_knowledge_point_links (M:N, "考察") ──► problem
       ▲                                                               │ 1:N
       │ method_knowledge_point_links (现有)                           ▼
  teaching_methods ◄── solution_technique_links (M:N, "用到") ──── solution
   (=技巧/模型)        │                                          (一题多解)
   └ variants (现有)   └ method_section_links (现有)              ↑ figures (题干/解步配图)
```

### 3.1 事实层（canonical）

#### `knowledge_points`（**改造**：去掉 section 绑定）

| 字段 | 变更 | 说明 |
|------|------|------|
| `section_id` | **移除** | 不再作为归属外键；改由 `section_knowledge_point_links` 表达 |
| `semantic_key` | **改语义** | 由"带 section 作用域"改为**基于内容**（规范化标题），使跨版本去重生效 |
| `code` | 暂不新增 | canonical 编码留作开放项（见 §8）；当前 `semantic_key` 已够去重 |

> ✅ 已实现：`section_id` 列由 `migrations._canonicalize_knowledge_points` **DROP**
> （回填链接后，先删索引再 `ALTER TABLE ... DROP COLUMN`；SQLite 3.35+ / PostgreSQL
> 均支持）。模型已不含该列，新建库直接为干净结构，旧库启动时一次性自动迁移。

#### `problems`（新增）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID PK | |
| `stem` | Text | 题干，**LaTeX / 含数学公式的 Markdown**（见 [§5 数学内容](#5-数学内容表示latex--图片--tikz)）|
| `problem_type` | String | 题型：选择 / 填空 / 解答 / 证明 等，或模型型（如"几何最值"）|
| `difficulty` | String | 难度标签（基础 / 中等 / 难，或数值）|
| `source_type` | String | 来源类别：课堂 / 试卷 / 教辅 / 题库 |
| `source_document_id` | FK→source_documents | 出处 |
| `has_answer` | Boolean | 抓取时是否含答案 |
| `semantic_key` | String, index | 内容去重键 |
| `aliases` | JSON | 别名 / 同题异形 |
| `evidence_id` | FK→evidence_snippets | 证据 |
| `confidence` / `source_count` / `last_seen_at` | | 同其它 canonical 表 |
| `human_locked` / `last_human_edited_at` / `review_status` | | 复核与锁定 |

#### `solutions`（新增）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID PK | |
| `problem_id` | FK→problems, index | 所属题目 |
| `approach_label` | String | 思路名（如"构造辅助线""数形结合"）|
| `steps` | JSON(list[str]) | 分步解题路径（LaTeX）|
| `final_answer` | Text | 最终答案 |
| `complexity` | String | 复杂度 / 优劣评估 |
| `source_teacher` / `source_org` / `source_region` | String | 来源（可得时）|
| `source_document_id` | FK→source_documents | 出处 |
| `evidence_id` / `confidence` / `review_status` / `human_locked` | | 同上 |

> 一题多解 = 一个 `problem` 下多条 `solution`。这与现有 `teaching_method_variants`
> 处理"同一方法的不同讲法"是同构机制——别重复造轮子，复用其设计经验。

#### `figures`（新增，可选；题干与解题步骤的配图）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID PK | |
| `owner_type` | String | `problem` \| `solution`（多态归属）|
| `owner_id` | UUID, index | 对应 problem / solution 的 id |
| `figure_kind` | String | `image` \| `tikz` |
| `image_path` | String | 存储的图片资源路径（`.data/figures/...`）|
| `tikz_code` | Text | AI 由图片生成的 TikZ 源码（可选）|
| `caption` | String | 图注 |
| `position` | Integer | 顺序 |
| `origin` | String | `original`（原图）\| `ai_generated`（AI 生成的 TikZ）|
| `confidence` | Float | AI 生成置信度 |

### 3.2 链接层（全部多对多）

| 表 | 关系 | 关键字段 | 唯一约束 |
|----|------|----------|----------|
| `section_knowledge_point_links`（新） | 小节 ⟷ 知识点（覆盖）| `relation_type`: introduce / reinforce / extend；`position`；`confidence`；`evidence_id` | (section_id, knowledge_point_id, relation_type) |
| `problem_knowledge_point_links`（新） | 题目 ⟷ 知识点（考察）| `relation_type`: primary / secondary；`confidence`；`evidence_id` | (problem_id, knowledge_point_id) |
| `problem_section_links`（新） | 题目 ⟷ 小节（弱关联）| `relation_type`: exercise_of / introduced_in；`confidence`；`evidence_id` | (problem_id, section_id) |
| `solution_technique_links`（新） | 解答 ⟷ 技巧（用到）| `relation_type`: primary / auxiliary；`confidence`；`evidence_id` | (solution_id, method_id) |
| `method_knowledge_point_links`（**现有**） | 技巧 ⟷ 知识点 | 沿用 | 沿用 |
| `method_section_links`（**现有**） | 技巧 ⟷ 小节 | 沿用 | 沿用 |

> 新链接表全部**仿照现有** [`method_section_links`](../mathscout/db/models.py#L323) 的形态
> （`relation_type` + `confidence` + `evidence_id` + 唯一约束），保持代码风格一致。

### 3.3 与现有概念的关系

- `student_skills`（S01–S16，如"运算能力""几何直观"）是**横切能力标签**，与"知识点"
  不是一回事，**不属于**这四维，保留为正交标签层。
- `region_adoptions`、`quality_snapshots` 等不受本次重构影响。

## 4. 抽取与调和的改动

### 4.1 枚举与候选

- `CandidateItemType`（[models.py](../mathscout/db/models.py#L62) 与
  [schemas.py](../mathscout/extraction/schemas.py#L63)）新增：`problem`、`solution`。
- 新增 pydantic 抽取模型 `ExtractedProblem` / `ExtractedSolution`（放
  [extraction/schemas.py](../mathscout/extraction/schemas.py)）：
  - `ExtractedProblem`：`stem`、`problem_type`、`difficulty`、`source_type`、
    `has_answer`、`knowledge_point_titles`（考察的知识点）、`section_hint`（弱关联线索）、
    `figures`、`evidence`、`confidence`。
  - `ExtractedSolution`：`problem_ref`、`approach_label`、`steps`、`final_answer`、
    `technique_titles`（用到的技巧）、来源字段、`evidence`、`confidence`。

### 4.2 调和（复用现有三段式，不另起炉灶）

题目 / 解答**完全复用**现有 `候选 → reconciliation → canonical` 管线：

- 去重靠 `semantic_key`（题目）/（problem_id + approach_label）（解答）。
- `problem ↔ knowledge_point` 的"考察"链接由 AI 标注，**置信度低、必须进复核**，
  绝不自动写 canonical。
- `solution ↔ technique` 链接：技巧用**已有 canonical 技巧库**匹配；匹配不到才走
  "新建技巧候选 → 复核"，避免一题一技巧污染库。

## 5. 数学内容表示（LaTeX + 图片 + TikZ）

题目与解答含大量公式和图形，是只抽散文式方法时不存在的新需求。约定：

- **公式**：统一存 **LaTeX**（题干、解步均为含数学的 Markdown / LaTeX 文本）。
- **图形**：
  - 原图作为**可选附件**存 `.data/figures/...`，`figures.image_path` 记录路径。
  - **可选**用 AI 将图片转成 **TikZ 源码**（`figures.tikz_code`，`origin=ai_generated`），
    便于无损缩放、版本化与再编辑。TikZ 生成是**可选增强步骤**，类比 OCR：未启用时
    只存原图，不阻断流程。
- 摄取层细节见 [ingestion.md](ingestion.md) 的"数学内容"一节。

## 6. 分期实施路线（按风险排序，不要一把梭）

### Phase A — 知识点 canonical 化 ✅ 已实现

风险最低、价值明确（修掉跨版本重复），且不抓任何新内容即可验证。

1. ✅ 新增 `section_knowledge_point_links` 表（`create_all` 自动建）。
2. ✅ 一次性迁移 `migrations._canonicalize_knowledge_points`（以"旧 `section_id` 列
   是否存在"为幂等开关）：
   - 按旧 `section_id` 为每条知识点回填一条 link（`relation_type=introduce`，原生 SQL）。
   - 先删索引再 `ALTER TABLE ... DROP COLUMN section_id`。
   - 把 `semantic_key` 重算为**基于内容**的键（规范化标题），并**合并**因此重复的 KP
     （保留一条 canonical，多余的小节/方法 link 改指向它后删除）。
3. ✅ 改 [template.py](../mathscout/importers/template.py)：按内容键全局去重，写 link 表。
4. ✅ 改读取方：admin 知识库页两处 join、`extract.py` 的
   `_link_knowledge_points_in_section` / `_link_by_text_match` 改走 link 表。

**验收（已通过）**：导入北师大版 6 册后，425 条原始知识点去重为 **417 条 canonical** +
**425 条覆盖 link**——8 个跨小节/跨册重复的知识点各自合并为一条、覆盖多个小节。
单测：`test_migrations`（迁移：回填/DROP/合并/幂等）、`test_template_shape`（导入 canonical
化 + 幂等）、`test_extract_mapping`（方法→知识点映射改走 link 表）。

> 注：纯标题去重偶尔会把同名异义判定合并（如 SAS 既是全等判定也是相似判定）。这类可由
> 人工"拆分"修正；去重粒度仍是 §8 的开放项。

### Phase B — 技巧 / 解答概念澄清（几乎不动表）

1. 文档 + 抽取 prompt 明确"技巧 = 可复用模型，按题去重技巧"。
2. 先建 `solutions` + `solution_technique_links` 空表（为 Phase C 铺路）。
3. `teaching_methods` 不动（已够表达技巧）。

### Phase C — 题目 + 解答抓取建模（高风险，**最后做，先小范围试点**）

1. 建表：`problems`、`solutions`、`figures`、`problem_knowledge_point_links`、
   `problem_section_links`、`solution_technique_links`。
2. 摄取层加数学内容支持（LaTeX 抽取 + 图片附件 + 可选图片→TikZ）。
3. 抽取层加 `ExtractedProblem` / `ExtractedSolution` + `CandidateItemType` 扩展。
4. 候选 → 调和 → canonical 走现有管线；题目-知识点"考察"链接强制进复核。
5. admin：题目库列表 + 题目详情页（渲染题干 / 解法列表 / 考察知识点 / 用到技巧）。
6. 先用**一个**范围可控的题源打通端到端，质量达标再扩量。

## 7. 已定的决策

| 决策 | 结论 |
|------|------|
| 题目数学内容怎么存 | **LaTeX 文本**；图片**可选**；可选用 AI 把图片生成 **TikZ 代码** |
| 题目是否含答案 | **题干 + 答案都抓**。目标是内部数据库，无版权问题；测试期仅用公开网站信息做测试，不涉版权 |
| 先做哪一期 | 先把**文档定稿并提交**，再开发；开发从 **Phase A** 起步 |

> 合规提醒：上面"无版权问题"的前提是**目标为内部数据库**。
> [architecture.md §9](architecture.md) 的对外发布合规约束（不转载受版权保护全文等）
> 在面向公开发布的场景仍然适用——内部留存与对外发布要分开对待。

## 8. 待办 / 开放问题

- `knowledge_points.code` 的编码规则（是否需要全局稳定编码，还是 semantic_key 足够）。
- 题目去重粒度：完全同题 vs 同题异形（数值/措辞微变）如何判定。
- TikZ 生成用哪个模型 / 走哪条 AI 通道（DeepSeek 是否够，还是需要多模态模型）。
- `figures` 用多态 `owner_type/owner_id` 还是给 problem / solution 各建一张图表——
  本文先按多态设计，落地时可再权衡。
