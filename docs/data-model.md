# 数据模型草案（Data Model）

本文概述规范化 schema。SQLAlchemy 模型位于 `mathscout/db/models.py`。

> ⚠️ **正在重构为"四维知识图谱"。** 下方"Canonical 教育表"描述的是**当前实现**
> （知识点硬挂在单个小节下）。目标模型——知识点 / 题目 canonical 化、新增题目与解答、
> 用链接表替代硬绑定——见 [knowledge-graph-redesign.md](knowledge-graph-redesign.md)，
> 并在本文 [§目标模型](#目标模型四维知识图谱) 概览。

## Canonical 教育表

- `textbook_series`
  - 出版社/版本族
  - 学制，如 六三制 或 五四制
  - 课程标准依据
- `books`
  - 年级、学期、版次标签
  - 映射到模板 id，如 `G7A`
- `chapters`
  - 映射到 id，如 `G7A-C1`
- `sections`
  - 映射到 id，如 `G7A-C1-S1`
- `student_skills`
  - 全局能力表，如 S01–S16
- `knowledge_points`
  - canonical 知识点记录
- `teaching_methods`
  - 一等公民的 canonical 解题方法
  - 存储共性方法标识、方法类型、摘要、通用步骤、适用题型、前置与来源计数
- `teaching_method_variants`
  - canonical 方法的、来源特定的教师版本
  - 保留不同的课堂讲法、步骤顺序、直觉、提醒与例题
- `method_section_links`
  - 方法 → 教材小节映射，带关系类型与置信度
- `method_knowledge_point_links`
  - 方法 → 知识点映射，带关系类型与置信度
- `region_adoptions`
  - 按地区/学校的、有证据支撑的教材使用记录

## 出处表（Provenance）

- `source_sites`
- `source_documents`
- `evidence_snippets`
- `extraction_runs`
- `review_items`
- `manual_edit_logs`
  - 每一次人工编辑的审计链
  - 存储表名、目标 id、动作类型、前载荷、后载荷、理由、操作人与回滚元数据

## 候选与调和表

- `candidate_knowledge_items`
  - 从单篇来源文档或分块中抽取的一个结构化候选
  - 存储项类型、规范化载荷、证据、置信度与抽取运行
  - 候选不可变；更正会生成新候选或复核编辑
- `reconciliation_decisions`
  - 对候选的 AI 决策：`skip`、`update`、`create_variant`、`create`、`conflict` 或 `review`
  - 存储匹配的 canonical id、理由、置信度与建议的数据库补丁
  - 提供"知识库为何变化或为何不变"的审计日志

## AI 编排表

- `orchestration_sessions`
  - 由人工目标创建的一个 AI 工作会话
  - 存储当前目标、目标范围、预算、状态、当前策略与停止条件
- `natural_language_commands`
  - 在后台指令中心输入的用户指令
  - 存储原始指令文本、AI 解读、结构化指令与执行状态
- `agent_decisions`
  - AI 决策的审计日志，如创建任务、调整来源优先级、暂停来源、重试失败任务、
    应用调和结果或停止会话
  - 每个决策都应包含理由、输入指标、策略检查与置信度
- `quality_snapshots`
  - 供编排器使用的周期性指标
  - 含章节覆盖率、来源产出、重复率、冲突率、平均置信度、登录拦截数、失败数、
    预算使用与新增趋势

> 说明：`region_adoptions` / `quality_snapshots` 等部分表当前"已建表但尚未被读写"，
> 是为规划功能预留的结构。

## 人工编辑规则

- 人工编辑是一等公民数据，而非系统外的批注
- canonical 知识点、教学方法、变体与映射都可在后台编辑
- 已编辑记录可标记为"人工锁定"，使 AI 不能自动覆盖
- AI 仍可对人工锁定记录提出更新，但这些建议必须进入复核
- 合并、拆分、删除与映射变更都应写入 `manual_edit_logs`
- 当复核审批修改了 canonical 数据时，也应写入编辑日志

## 作业表

- `crawl_jobs`
- `crawl_tasks`

## 重要关系

- 一个教材系列有多个册
- 一个册有多个章
- 一个章有多个节
- 一个节有多个知识点
- 教学方法可链接到多个小节与知识点
- 一个 canonical 教学方法可有多个教师/来源变体
- 方法调和应保留有意义的变体，而非过度合并
- 每条抽取记录应尽量链接到至少一个证据片段
- 地区采用记录必须链接证据，而非仅凭自由文本
- 抓取抽取的输出不应直接写入 canonical 表
- 新抽取输出先成为候选，再由调和环节决定 跳过/更新/创建/标记冲突/请求复核
- canonical 记录通过证据/来源计数跟踪重复出现，候选记录则保留精确的、有来源支撑的抽取结果
- 人工主要通过 `natural_language_commands`、看板与复核队列交互；编排器把方向翻译成结构化计划
- AI 执行必须可通过 `agent_decisions` 审计、可通过 `quality_snapshots` 度量
- 人工变更必须可通过 `manual_edit_logs` 审计；AI 调和在决定 跳过/更新/请求复核 时应参考这些日志

## 目标模型（四维知识图谱）

> 完整设计、字段清单、迁移与分期实施见
> [knowledge-graph-redesign.md](knowledge-graph-redesign.md)。此处只给概览。

把覆盖范围升级为四个维度：

| 维度 | 实体 | 与教材版本的关系 |
|------|------|------------------|
| 教材 / 章 / 节 | `textbook_series`→`books`→`chapters`→`sections` | **版本相关**：只决定顺序与选材 |
| 知识点 | `knowledge_points`（改造为 canonical）| **版本无关**：跨版本唯一、共享 |
| 题目 | `problems`（新增）| **版本无关**：弱关联到小节 |
| 解题技巧 / 模型 | `teaching_methods`（沿用）| **版本无关**：跨题复用 |

### 关键变化

1. **知识点 canonical 化**：移除 `knowledge_points.section_id` 硬绑定，改用
   `section_knowledge_point_links`（M:N，带 `relation_type` introduce/reinforce/extend）；
   `semantic_key` 改为**基于内容**，使同一知识点在多版本只存一条。
2. **新增题目 `problems`**：题干为 LaTeX，含题型 / 难度 / 来源类别 / 是否含答案；
   通过 `problem_knowledge_point_links`（"考察"）与 `problem_section_links`（弱关联）连接。
3. **新增解答 `solutions`**：一题多解；通过 `solution_technique_links` 关联到所用技巧
   （= `teaching_methods`）。**解答 ≠ 技巧**：解答是题目专属，技巧是跨题复用模型。
4. **新增 `figures`**：题干 / 解步配图，存原图路径与可选的 AI 生成 TikZ 源码。
5. **候选 / 调和 / 复核管线全部复用**：题目与解答走现有
   `candidate → reconciliation → canonical` 三段式；题目↔知识点"考察"链接强制进复核。

### 新增 / 改造的表一览

- 改造：`knowledge_points`（去 section 绑定 + 内容键去重）
- 新增 canonical：`problems`、`solutions`、`figures`
- 新增链接：`section_knowledge_point_links`、`problem_knowledge_point_links`、
  `problem_section_links`、`solution_technique_links`
- 沿用：`teaching_methods`（= 技巧）、`teaching_method_variants`、
  `method_section_links`、`method_knowledge_point_links`
- 抽取：`CandidateItemType` 增加 `problem` / `solution`；新增
  `ExtractedProblem` / `ExtractedSolution`
