# MathScout 架构设计

本文是 MathScout 的总体设计与愿景。**注意区分"愿景"与"当前实现"**：下方对照表
给出每项能力的实现状态，后续各节用 ✅（已实现）/ 🚧（部分实现）/ 📋（规划中）
标注。实现状态以 [development-status.md](development-status.md) 为准。

## 0. 实现状态对照表

| 能力 | 状态 | 说明 |
|------|------|------|
| 三阶段流水线（爬取 / 提取 / 复核）| ✅ | `pipeline_status` 作为阶段交接信号，可独立重跑 |
| 教材结构导入（`.template`）| ✅ | 系列 / 册 / 章 / 节 / 知识点 / 学生能力 |
| 单 URL 与持久化爬取作业 | ✅ | 支持暂停 / 续跑 / 取消 |
| 深度抓取（同域、同路径前缀链接发现）| ✅ | 基于关键词规则打分，非 LLM |
| HTML / 数字版 PDF 解析 | ✅ | trafilatura / PyMuPDF |
| 文档类型识别（magic/Content-Type/扩展名 + PDF 文字层探测）| ✅ | 见 [ingestion.md](ingestion.md) |
| Office（docx/pptx/xlsx）→ Markdown | ✅ | 经 markitdown |
| 附件下载（课件/教案/学案，发现阶段识别入队）| ✅ | `DOWNLOAD_ATTACHMENTS` 开关 |
| 扫描版 PDF / 图片 OCR | 🚧 | 经 markitdown 调 Azure 文档智能，配置开关；未配置标记 needs_ocr |
| Schema 约束的方法抽取（DeepSeek）| ✅ | 失败回退规则抽取器 |
| 候选项 → 主知识库的规则调和 | ✅ | 按语义键判断 创建 / 变体 / 跳过 |
| 失败任务指数退避重试 | ✅ | `CrawlTask.not_before` |
| 人工复核队列（通过 / 需编辑 / 拒绝）| ✅ | 写入 `ManualEditLog` |
| 自然语言目标 → 受监督爬取作业 | 🚧 | **规则编排**，非 LLM 推理 |
| 多 Agent 编排（15+ Agent）| 📋 | 仅类型契约，无运行实现 |
| LLM 驱动的调和 / 质量监控 / 自动策略调整 | 📋 | 仅有 schema / 类型定义 |
| 登录 Cookie 流程（Playwright）| 📋 | 未实现 |
| robots / 按域限速 | 📋 | 未接入作业执行器 |
| PostgreSQL + Alembic + pgvector | 📋 | 当前仅 SQLite + 手写迁移 |
| 独立 worker / 并发编排 | 📋 | 当前用 FastAPI `BackgroundTasks` |
| 人工编辑表单、详情页、检索过滤 | 📋 | 仅有列表页 |

## 1. 产品范围

MathScout 的定位是**由 AI 辅助维护的教学知识库系统**，而不只是爬虫。抓取只是输入层，
产品的核心是收集、保留并组织多样的教师方法知识。知识点与教材结构提供索引框架，
但系统应当为"收集与保留不同教师的解题/教学经验"而优化。

规范化的知识图谱应包含：

- 教材版本、学制、版次标签与地区采用证据
- 册别、章、节，以及跨学期依赖关系
- 教学方法、解题经验、常见误区、例题与题型模式
- 来自不同教师/来源的方法变体
- 来自课程标准、教材目录、教师用书、教案的知识点
- 学生能力：数感、建模、几何直观、证明、分类、检验等
- 每条抽取结论的来源出处

`.template` 目录已提供了一个良好的初始规范层级：

```text
教材系列 -> 册/学期 -> 章 -> 节
节 -> 知识点
节 -> 学生能力引用
章/节 -> 跨学期衔接
```

MathScout 在此基础上扩展为有来源支撑的数据库，新增文档、证据片段、候选记录、
调和决策、抽取运行记录与复核状态。

### 解题方法是一等公民

系统**不应**把不同老师的讲法压平成一份平淡的摘要。一个 canonical（主）方法表示
共性方法，变体则保留有价值的差异：

- 教师措辞或教学顺序
- 不同的切入点或直觉
- 不同的辅助线、模型或变换路径
- 不同的适用题型
- 常见误区或课堂提醒
- 可得时记录来源教师、学校、地区与文档出处

例如两位老师都讲"数形结合比较有理数大小"，但一位用数轴距离直觉、另一位用
符号/绝对值分类。它们应映射到同一小节、可能映射到同一主方法，但若课堂方法
确有差异，就保留为不同变体。

## 2. 运行模型

MathScout 的**愿景**是 AI 主导的编排模式：

```text
人工自然语言目标
  -> AI 编排器解读目标、范围、预算与质量标准
  -> 策略护栏（PolicyGuard）检查硬约束
  -> AI 编排器创建 爬取 / 提取 / 调和 任务
  -> Worker Agent 执行任务
  -> 质量监控报告覆盖率、新增率、冲突与失败模式
  -> AI 编排器调整策略或决定停止
  -> 人工通过后台监控、纠偏、审批或暂停
```

> **当前实现**：`AIOrchestratorAgent.plan()` 是**确定性规则编排**，无论目标内容如何，
> 都会按固定顺序产出"发现链接 → 创建爬取作业 → 提取 → 调和"等动作，并把每步写入
> `agent_decisions`。质量监控、自动策略调整、停止条件判断等均为规划，尚无运行实现。

愿景中 AI 可主动管理的内容：爬取目标选择与优先级、单来源探索深度（在配额内）、
任务分配、抽取与调和排序、质量监控与覆盖缺口检测、重试/暂停/续跑/停止决策，
以及基于重复率、来源质量、冲突与预算的策略调整。

无论 AI 还是规则编排，系统都用确定性代码强制以下**硬护栏**：

- 不绕过验证码、付费墙或 DRM
- 不跨域复用 Cookie
- 不忽略禁用域名、限速或爬取预算
- 未经人工明确批准不做破坏性删除
- 高风险冲突未经复核不发布
- 不把受版权保护的完整资源作为 canonical 产出存储或再发布

## 3. 来源策略

采用分级来源策略。

### Tier 1：官方基线

- 教育部课程标准。
- 教育部教学用书目录。
- 国家中小学智慧教育平台公开元数据与公开课程资源。
- 省、市、区教育局的教学用书选用或征订通知。

这些来源定义 canonical 基线，应优先抓取，并用于校验教材版次与地区采用情况。

### Tier 2：出版社与教材配套来源

- 各版本出版社页面：人教版、北师大版、华东师大版、北京版、湘教版、冀教版、
  鲁教版、苏科版、沪科版、浙教版、青岛版等。
- 公开教材目录页、勘误、培训通知、教师培训课件与样章资源。

这些来源对版本元数据与章节结构有用，但应与"地区采用证据"分开保存。

### Tier 3：公开教师资源

- 公开教案、微课、教学反思、公开课记录、公开学案/任务单、教研文章。
- 教育局教研网站与学校网站的公开内容。

大部分经验知识来自这一层。系统应保存短证据片段与结构化摘要，**不盲目转载受版权
保护的完整文档**。

### Tier 4：登录受限来源

只有在用户有权访问时才支持登录受限来源。MathScout 应检测登录墙，将来源标记为
`login_required`，等待用户提供浏览器 Cookie 配置或 Playwright storage state，
**不绕过验证码、付费墙或访问控制**。

## 4. 数据模型

核心表：

- `source_sites`：域级来源配置、访问策略、爬取优先级、限速。
- `source_documents`：一个 URL/PDF/视频/页面，含抓取状态、校验和、原始文件路径、抽取文本路径。
- `evidence_snippets`：用于支撑抽取结论的、有来源的短片段。
- `textbook_series`：出版社/版本族，如"北师大版初中数学（六三制）"。
- `books`：年级与学期册，如 G7A 七年级上册。
- `chapters` / `sections`：教材结构。
- `knowledge_points`：与小节对齐的规范化概念。
- `student_skills`：全局能力表，初始兼容 `.template` 的 S01–S16。
- `teaching_methods`：解题技巧、教学方法、误区与题型模式。
- `teaching_method_variants`：链接到 canonical 方法的、来源特定的教师讲法。
- `method_section_links`：方法 → 教材小节映射。
- `method_knowledge_point_links`：方法 → 知识点映射。
- `region_adoptions`：省/市/区/校的采用记录，含证据与置信度。
- `candidate_knowledge_items`：从单篇新解析文档抽取出的结构化记录。
- `reconciliation_decisions`：跳过/更新/创建/冲突/复核的 AI 决策。
- `orchestration_sessions`：由人工目标创建的 AI 工作会话。
- `natural_language_commands`：用户指令、AI 解读与生成的计划。
- `agent_decisions`：AI 调度、策略、重试、停止与质量决策的审计日志。
- `quality_snapshots`：覆盖率、重复率、冲突率、抽取置信度、来源质量等指标。
- `manual_edit_logs`：人工对 canonical 知识、方法、变体、链接与来源元数据的编辑。
- `crawl_jobs` / `crawl_tasks`：编排与重试跟踪。
- `extraction_runs`：模型、Prompt 版本、输入文档、输出哈希与复核状态。
- `review_items`：人工校验队列。

每条生成的知识记录都应有：来源文档 id、尽量带证据片段 id、抽取器版本、置信度、
复核状态、来源分歧时的冲突标记，以及人工整理后的编辑状态与锁定字段。

> 说明：上述表大多已在 `mathscout/db/models.py` 中定义。其中
> `region_adoptions` / `quality_snapshots` 等部分表当前"已建表但尚未被读写"，
> 属于为规划功能预留的结构。

## 5. 流水线

```text
人工目标 / 自然语言指令
  -> AI 编排器（当前为规则编排）
  -> 策略护栏
  -> 来源发现 / 任务规划
  -> 爬取 Agent
  -> 解析 Agent
  -> 抽取 Agent
  -> 候选知识项
  -> 与已有库检索比对
  -> 调和 Agent
  -> 决策：skip | update | create | conflict | review
  -> 质量监控
  -> AI 策略调整 / 停止决策
  -> 人工后台与高风险决策复核
  -> 发布到 canonical 知识图谱
```

### Fetchers（抓取器）

- `HttpFetcher`：静态 HTML、PDF、已知 API 与简单下载。✅（当前用 Scrapling `AsyncFetcher` 实现）
- `BrowserFetcher`：基于 Playwright，渲染重 JS 或登录受限页面。📋
- `ManualUploadFetcher`：用户上传的 PDF/DOC/PPT。📋

所有 Fetcher 都应产出 `source_document` 记录，绝不直接创建 canonical 知识记录。

### Parsers（解析器）

抓取后由统一的**摄取/转换层**处理（见 [ingestion.md](ingestion.md)）：先做文档类型
识别，再按类型选最擅长的工具转成 Markdown。

- HTML：trafilatura 优先，BeautifulSoup 兜底。✅
- 数字版 PDF：PyMuPDF 文本抽取。✅
- 扫描版 PDF / 图片：经 markitdown 调 Azure 文档智能 OCR。🚧（配置开关；未配置标记 needs_ocr）
- DOCX/PPTX/XLSX：经 markitdown 转 Markdown。✅
- 视频：先存元数据；仅在有字幕或合法转录时做转写。📋

### Extractors（抽取器）

使用受 schema 约束的抽取，**不要**让 LLM 输出自由散文。每个抽取器返回匹配某个
schema 的 JSON：`TextbookStructureExtraction`、`KnowledgePointExtraction`、
`TeachingMethodExtraction`、`RegionAdoptionExtraction`、`SkillMappingExtraction`。

> **当前实现**：已实现教师方法抽取（`TeachingMethodExtraction`），见
> [extraction/prompts.md](../mathscout/extraction/prompts.md)。其余 schema 为规划。

抽取输出不会立即成为 canonical，而是先成为候选项。教师方法抽取应捕获：方法标题与
类型、可得时的教师/来源、教材系列/册/章/节/知识点对齐、适用题型、分步解题路径、
方法为何有效、何时不适用、能避免的常见错误、前置能力、证据片段。

### 调和 Agent（Reconciliation）

调和是核心后端环节。对每个候选项：

1. 用标题、别名、章节对齐、能力引用、方法步骤与证据片段构造语义检索查询。
2. 从 `knowledge_points`、`teaching_methods`、`student_skills` 与地区采用表中检索可能的已有记录。
3. 在教材版本/册/章/节、概念含义与别名、方法步骤与适用题型、证据来源权威性与新鲜度、
   置信度与复核状态等维度上比较候选与已有记录。
4. 产出一个明确决策：
   - `skip`：重复或证据更弱；只更新 `last_seen_at` 与来源计数。
   - `update`：同一 canonical 项，但表述更好、证据更强或有新适用题型。
   - `create_variant`：同一 canonical 方法，但教师讲法有值得保留的明显差异。
   - `create`：确实是全新的知识点/方法/能力/地区采用记录。
   - `conflict`：来源与已有 canonical 数据冲突。
   - `review`：匹配含糊或置信度低。
5. 写入一条 `reconciliation_decision`，含理由、候选 id、匹配 canonical id、置信度与建议补丁。

只有低风险的 `skip` 才应全自动。对教学方法，当来源带来真实教学差异时，
应优先 `create_variant` 而非激进合并。`update`/`create`/`create_variant` 只有在用
复核数据验证过置信度阈值后才能自动应用；`conflict` 永远进复核队列。

> **当前实现**：`extract.py` 内联了一个**基于语义键**的规则调和：命中已有方法则记
> `skip`，否则按教学方法创建主记录或变体，并写入 `reconciliation_decisions`。
> 基于相似度阈值/向量检索的完整调和为规划。

### AI 编排器（Orchestrator）

编排器是主运行时管理者，接收如下人工目标：

```text
优先把北师大版七年级上册公开资料抓完，重点补充有理数和一元一次方程的教师解题方法。
如果连续 50 篇资料没有新增方法，就暂停该来源并换省级教研站点。
```

并把它翻译成结构化计划：目标教材系列/册/章/节、要用的来源分级与域名、爬取深度/
批量/预算、覆盖率与最小证据数等质量目标、停止条件、复核阈值。

每个编排决策都写入审计日志。后台应展示 AI（或规则）决定了什么、为什么、下一步要做
什么、由哪条规则或用户指令授权。

> **当前实现**：编排为确定性规则（见第 2 节）。"连续 N 篇无新增就换源"这类基于
> 质量指标的自动策略调整尚未实现。

### 人工复核与编辑

后台必须支持人工直接纠正。AI 可以管理流水线，但人工整理是数据模型的一部分。

人工编辑能力（愿景）：浏览教材树/知识点/canonical 方法/教师变体；编辑方法的标题、
类型、摘要、步骤、适用题型、前置与提醒；编辑方法的知识点与小节映射；合并重复方法
或拆分被过度合并的方法；审批/拒绝/改写 AI 调和建议；锁定已整理记录使其不被自动覆盖；
接受 AI 方法/变体前查看来源证据；查看变更历史并对比前后载荷。

人工编辑后的 AI 行为：人工锁定的记录只接收 AI 建议、不被直接更新；AI 应把人工
认可的表述与映射视为更高权威；后续调和在提建议时应引用人工编辑历史；破坏性的
编辑、合并、拆分都需要人工明确操作。

> **当前实现**：已实现复核队列的"通过 / 需编辑 / 拒绝"，并写入 `ManualEditLog`
> （见 `review.py`）。结构化编辑表单、合并/拆分、记录锁定为规划。

## 6. Agent 设计 📋（多为规划）

"子 Agent"概念可干净地映射为队列 worker：每个 Agent 是一个专注的 worker，读取任务、
写出结构化输出、记录置信度。愿景中的 Agent 列表：

- `AIOrchestratorAgent`：持有当前目标，创建任务、改优先级、决定续/停。🚧 已有规则版
- `NaturalLanguageCommandAgent`：把用户指令转为结构化指令。🚧
- `PolicyGuardAgent`：拦截违反访问/版权/预算/破坏性变更规则的动作。🚧 已有链接级护栏
- `SourceDiscoveryAgent`：发现候选官方与公开来源；从种子页按规则打分发现链接。✅
- `LoginGateAgent`：检测登录/验证码/付费墙状态并请求 Cookie。📋
- `CrawlAgent`：按域限速抓取来源文档。🚧（抓取 ✅，限速 📋）
- `ParseAgent`：把原始页面/PDF 转为文本与版面感知分块。✅（分块 📋）
- `CurriculumMapperAgent`：把文本对齐到册/章/节。📋
- `KnowledgeAgent`：抽取知识点与前置关系。📋
- `MethodAgent`：主抽取 Agent，抽取教师解题方法、变体、误区与适用题型。✅
- `CourseMappingAgent`：把方法映射到版本/章/节/知识点/能力。🚧 已有简单推断
- `RegionAdoptionAgent`：从教育局通知抽取地区教材使用情况。📋
- `RetrievalAgent`：从 canonical 表与向量索引检索候选匹配。📋
- `ReconciliationAgent`：决定 skip/update/create/conflict/review 并提建议补丁。🚧 已有规则版
- `DedupValidateAgent`：校验调和决策、合并重复、标记冲突、分配复核优先级。📋
- `QualityMonitorAgent`：度量覆盖率、重复率、冲突率、来源价值与抽取置信度。📋
- `StopConditionAgent`：基于目标与质量指标推荐 停/暂停/续。📋

实现路线：先用队列任务（如需更显式的 Agent 状态，再在同一任务接口背后引入
LangGraph 或自定义状态机）。

## 7. 登录与 Cookie 流程 📋（未实现）

1. Fetcher 收到 401/403、登录跳转、验证码标记或空的受保护页面。
2. 创建 `login_required` 类型的 `review_item`。
3. 后台展示来源 URL 与域名。
4. 用户在浏览器手动登录。
5. 用户导出 Playwright storage state 或粘贴该域的 Cookie。
6. MathScout 加密存储 Cookie 配置。
7. 爬取作业带该 Cookie 配置续跑。

Cookie 配置应按域名与有效期限定范围，不跨域共享，不写入日志。

## 8. 后台 UI

首批后台视图（部分已实现，部分规划）：控制台、AI 指令中心、AI 计划视图、来源、
爬取任务、文档、复核队列、调和队列、知识浏览、方法库、编辑表单、变更日志、
地区地图/表、质量监控。

后台保持简洁。在数据量或复核流程对前端提出更高要求之前，服务端渲染的
FastAPI/Jinja 页面已经够用。

> **当前实现**：控制台、智能爬取(Agent)、爬取任务及详情、来源站点、已抓文档、
> 复核队列、方法库、知识库、决策记录、变更记录均已上线（只读列表 + 基本操作）。
> 调和队列、编辑表单、地区表、质量监控为规划。

## 9. 版权与合规

爬虫应保守：在适用处尊重 robots.txt、按域限速、保持完整原始文档私有、只存来源 URL
与短证据片段供复核、对教学方法做摘要与转写而非整篇转载、不绕过付费墙/验证码/DRM/
平台条款、保留署名与出处。

这点很重要：教材 PDF、教师用书与商业教学资源即便能在线浏览，通常仍受版权保护。

> **当前实现**：已做"只存短证据片段 + 摘要、不直接发布全文"。robots / 按域限速
> 尚未接入作业执行器（见 development-status.md 待办）。

## 10. 开发路线图

### Phase 0：骨架 ✅
项目结构、配置、数据库模型；导入 `.template` JSON 到 canonical 表。

### Phase 1：官方基线 🚧
种子官方来源；抓取教育部目录与课标 PDF；抓取省/市教学用书通知；建地区采用证据表；
加入 AI 指令会话与初版编排规划。

### Phase 2：公开资源抓取 🚧
公开教师资源来源注册；严格限速抓取 HTML/PDF；解析与分块文档。

### Phase 3：抽取与复核 🚧
实现 JSON-schema 抽取；加入候选记录、检索、调和决策、去重与冲突检测；构建复核 UI。

### Phase 4：规模化 📋
按域分组的并发 worker；方法与例题的向量检索；增量重抓与新鲜度检查；按版本/章的
质量报告；基于质量快照与人工自然语言反馈的 AI 自适应策略。

## 11. 待定决策

- 北师大版之后优先做哪些教材版本？
- embedding 存在主 PostgreSQL（pgvector）还是独立向量库？
- 登录来源是仅限私有研究，还是可贡献到共享发布的摘要？
- 例题与题面应逐字存储、改写，还是仅作抽取方法的证据？
- 早期哪些动作可由 AI 自动应用，哪些必须保持"仅复核"，直到积累足够审计数据？
