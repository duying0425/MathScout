# 开发状态（Development Status）

最近更新：2026-06-08。

## 本次更新（2026-06-08）— Phase C 切片 4：图片附件抽取（数学内容摄取·非多模态）

补上抽取器的图片缺口：`figures` 表/调和/UI 早已就绪，但抽取器从不产出 figure。本切片
让规则抽取器从题干/解答里把图片抽出来（LaTeX 仍作为文本原样保留；图片→TikZ 多模态留后续）。

- **抽取器**（`extraction/problem_rule_based`）：新增 `_extract_figures`——解析 Markdown
  `![alt](src)` 与 HTML `<img src=…>`，把图片存为 `ExtractedFigure`（`image`/`original`），
  并从题干/解题步骤文本中**剥离图片标记**（题干图 → 题目配图，解答步骤图 → 该解答配图）。
- **验证**：`ruff` 干净（4 个 E501 为既有）；`pytest` 45 全过（新增图片抽取用例）。
  端到端实测：含 Markdown 题干图 + HTML 解答图的文本 → 2 条 `Figure`，归属分别为
  `problem`/`solution`，题目详情页可见。
- **下一步**：AI 抽取器、图片→TikZ（多模态，需定模型/通道）、小范围真实题源试点。

## 此前更新（2026-06-08）— Phase C 切片 3：题目库 UI + 考察知识点人工复核

把题目/解答数据可视化并闭合 KP 复核门控（切片 1 把"题目考察知识点"挂起为
`ReviewItem`，本切片提供人工确认/拒绝的入口）。

- **路由**（`admin/routes.py`）：`GET /admin/problems` 列表（题干/题型/来源/含答案/解法数/
  来源数/复核/考察待复核徽标）；`GET /admin/problems/<id>` 详情（题干、解法+步骤+用到技巧、
  考察知识点、弱关联小节、配图含 TikZ）；`POST .../confirm-knowledge-points` 确认建立
  `problem_knowledge_point_links`，`POST .../reject-knowledge-points` 拒绝——均写 `ManualEditLog`
  （`approve_ai_change` / `reject_ai_change`）。
- **导航**（`_header.html`）：Phase 3 子导航新增「题目库」。
- **模板**：`templates/admin/problems.html`、`problem_detail.html`。
- **验证**：`ruff` 干净（4 个 E501 为既有）；`pytest` 44 全过（新增 `test_problem_admin`：
  详情装配、确认建链接+写日志、拒绝不建链接）。实盘起服务器 curl 验证：列表/详情 HTTP 200、
  确认 POST 303 后详情出现「✅ 勾股定理」（链接已建）。
- **下一步**：摄取层数学内容（LaTeX + 图片 + 可选图片→TikZ）、AI 抽取器、小范围试点。

## 此前更新（2026-06-08）— Phase C 切片 2：规则版题目抽取器（文本→canonical 端到端）

把上一切片的调和骨架"喂活"：新增规则版抽取器，离线可测地从清洗文本产出题目/解答。

- **抽取器**（`extraction/problem_rule_based.RuleBasedProblemExtractor`）：按标记切分——
  题目起始 `例N / 【例N】/ 第N题 / 题N / "N." / "N、"`；解答起始 `解：/解答/解析/证明/
  略解/答案`（单字"解/证/答"必须带冒号，避免把"解方程""证书"误判为解答）；多解
  `解法一/方法二…`；最终答案 `答案：X / 答：X`。规则版置信度 0.4。
- **端到端入口**（`pipeline/problem_extract.extract_and_reconcile_problems`）：规则抽取 + 调和
  一步到位，文本 → canonical 题目/解答/链接。AI 抽取器只要产出同一 `ExtractedProblem`
  契约即可无缝替换。
- **验证**：`ruff` 干净（4 个 E501 为既有）；`pytest` 41 全过（新增 `test_problem_rule_based`：
  题干/解答/答案解析、单字"解"不误切、文本→canonical 三用例）。
- **下一步**：摄取层数学内容（LaTeX + 图片 + 可选图片→TikZ）、AI 抽取器、题目库 UI。

## 此前更新（2026-06-08）— Phase C 切片 1：题目抽取契约 + 调和骨架

四维知识图谱重构第三期，按切片推进（先确定性、可测的骨架；高风险的真实抓取/多模态
TikZ/UI 留后续切片）。本切片只接**离线、确定性**的调和骨架，不碰网络与多模态。

- **抽取契约**（`extraction/schemas.py`）：新增 `ExtractedProblem` / `ExtractedSolution` /
  `ExtractedFigure`；`CandidateItemType` 扩展 `problem` / `solution`（pydantic Literal +
  `db/models.py` 枚举）。
- **调和骨架**（`pipeline/problem_extract.ProblemReconciler`）：把 `ExtractedProblem` 调和进
  canonical 事实层，复用"候选 → reconciliation → canonical"三段式：
  - 题目按 `semantic_key` 去重（重复则 `source_count++`）；解答按思路/步骤去重；配图按
    多态归属落库。
  - **题目↔小节**：能从教材线索定位到小节就建软链接（弱关联）。
  - **解答↔技巧**：只链接到**已有** canonical 技巧（按语义键匹配），匹配不到**不新建**，
    避免一题一技巧污染技巧库。
  - **题目↔知识点（考察）**：AI 标注置信度低，**不自动写链接**，改生成一条
    `ReviewItem`（`item_type=problem_knowledge_point`，含已匹配的知识点 id）入复核。
- **验证**：`ruff` 干净（4 个 E501 为既有）；`pytest` 38 全过（新增 `test_problem_reconcile`：
  创建/链接/复核门控、去重 + 忽略未知技巧两用例）。
- **下一步**：真实抽取器（规则/AI 从清洗文本产出 `ExtractedProblem`）、摄取层数学内容
  （LaTeX + 图片 + 可选图片→TikZ）、题目库 UI；再小范围试点打通端到端。

## 此前更新（2026-06-08）— Phase B 实现：题目/解答事实层 schema + 技巧概念澄清

四维知识图谱重构第二期。把题目/解答这一 canonical 事实层的**完整 schema 建出来**
（空表、外键自洽），并澄清"解答 ≠ 技巧"，为 Phase C（抓取/抽取/UI）铺路。

- **模型**（`db/models.py`）：新增 `Problem`（题干 LaTeX、题型/难度/来源类别/是否含答案）、
  `Solution`（一题多解、思路/步骤/最终答案）、`Figure`（题干/解步配图，原图 + 可选 TikZ，
  多态归属）、以及 3 张链接表 `problem_knowledge_point_links`（考察）、
  `problem_section_links`（弱关联）、`solution_technique_links`（用到）。
  `teaching_methods`（=技巧）/ `knowledge_points` 等既有表不动。
- **依赖说明**：原计划只建 `solutions` + `solution_technique_links`，但 `solutions.problem_id`
  外键指向 `problems`，`create_all` 需被引用表存在，故把事实层 schema 一次建齐；Phase C
  因此只接**行为**（摄取/抽取/复核/UI），不再重复建表。
- **概念澄清**（`extraction/ai_method_extractor.py`）：System Prompt 新增规则 11 +
  method_type 说明——"解题技巧/模型是跨题复用方法（将军饮马、手拉手…），不是某道题的
  一次性解答，不要一题一技巧"。
- **验证**：`ruff` 干净（4 个 E501 为既有）；`pytest` 36 全过（新增 `test_phase_b_schema`：
  6 张新表建出 + 题目/解答/配图/三种链接落库与关系可用）。`init-db` 实盘确认 6 张新表
  外键自洽、知识点表已无 `section_id`。
- **下一步**：Phase C —— 摄取层数学内容（LaTeX + 图片 + 可选图片→TikZ）、抽取
  `ExtractedProblem`/`ExtractedSolution` + `CandidateItemType` 扩展、候选→调和→canonical、
  题目库 UI；先小范围试点。

## 此前更新（2026-06-08）— Phase A 实现：知识点 canonical 化（425→417）

落地四维知识图谱重构的第一期。知识点从"硬挂在单个小节"升级为 **canonical（跨版本唯一）**，
小节与知识点改为多对多覆盖关系。

- **模型**（`db/models.py`）：移除 `KnowledgePoint.section_id`；新增
  `SectionKnowledgePointLink`（小节⟷知识点，`relation_type`: introduce/reinforce/extend，
  仿 `method_section_links`）；`Section.knowledge_point_links` / `KnowledgePoint.section_links`
  关系替换旧的 `knowledge_points` 直连关系。
- **迁移**（`db/migrations._canonicalize_knowledge_points`）：以"旧 `section_id` 列是否
  存在"为幂等开关——按旧 `section_id` 原生 SQL 回填链接 → 先删索引再
  `ALTER TABLE ... DROP COLUMN section_id`（SQLite 3.35+/PG 支持，已实测 3.50.4）→
  `semantic_key` 重算为基于内容 → 合并重复知识点（小节/方法链接改指向 canonical 后删除）。
- **导入**（`importers/template.py`）：按内容键全局去重（同一知识点跨册/版本只建一条），
  写 `section_knowledge_point_links`；导入幂等。新增 `section_links` 统计项。
- **读取方**：`admin/routes.py` 知识库页两处 join、`extract.py` 的
  `_link_knowledge_points_in_section` / `_link_by_text_match` 均改走链接表。
- **验证**：`ruff` 干净（4 个 E501 为既有、与本次无关）；`pytest` 34 全过（新增
  `test_migrations` 迁移用例、`test_template_shape` 导入 canonical 化用例，更新
  `test_extract_mapping` seed 改用链接表）。实盘 `init-db + import-template`：北师大 6 册
  **425 条原始知识点 → 417 条 canonical + 425 条覆盖 link**，8 个跨小节/跨册重复各合并为
  一条；`section_id` 列已 DROP；知识库页查询正常。
- **已知**：纯标题去重偶有同名异义合并（如 SAS 全等/相似判定），可人工"拆分"修正；
  去重粒度仍是开放项。下一步：Phase B（技巧/解答概念澄清，建 `solutions` 空表）。

## 此前更新（2026-06-08）— 设计定稿：四维知识图谱重构（文档先行）

重新梳理数据关系后，确定把覆盖范围从"以教学方法为核心"升级为**四维知识图谱**：
教材/章/节（版本相关，仅决定顺序）、知识点（版本无关、canonical）、题目（版本无关、
弱关联小节）、解题技巧/模型（跨题复用）。本次**只落文档、未改代码**，按用户要求
"文档先行，便于新对话/其他开发者接手"。

- **新增主设计文档** [knowledge-graph-redesign.md](knowledge-graph-redesign.md)：单一事实
  来源。含目标 schema（改造 `knowledge_points`、新增 `problems`/`solutions`/`figures`
  与 4 张链接表）、抽取/调和改动、数学内容（LaTeX+图片+可选 TikZ）、**分期路线**
  （Phase A 知识点 canonical 化 → B 技巧/解答概念澄清 → C 题目+解答），以及已定决策。
- **核心结论与原则**：
  - 教材是**视图**、知识点与题目是**稳定事实**；知识点必须 canonical（跨版本唯一）。
  - 当前结构矛盾：`knowledge_points.section_id` 硬绑定 + `semantic_key` 带 section
    作用域（见 `importers/template.py`），导致同一知识点跨版本重复——Phase A 优先修。
  - **解答（Solution）≠ 解题技巧（Technique）**：解答题目专属、可一题多解；技巧
    （= 现有 `teaching_methods`）跨题复用。解答经 `solution_technique_links` 引用技巧。
- **已定决策**：题干存 LaTeX、图片可选、可选用 AI 把图片生成 TikZ；题干+答案都抓
  （目标为内部数据库无版权问题，测试期仅用公开信息）；开发从 **Phase A** 起步。
- **同步更新**：`data-model.md`（目标模型一节）、`architecture.md`（状态表/产品范围/
  数据模型/路线图/待定决策）、`ingestion.md`（数学内容章节）、`CLAUDE.md`（范围4维+约定）。
- **下一步（开发）**：实现 Phase A —— 新增 `section_knowledge_point_links`、数据迁移
  （现有 KP 按 section 生成 link + 内容键去重合并）、改 `template.py` 与读取方、停用
  `section_id`。验收：导入两个版本后共有知识点只占一条 canonical 记录。

## 此前更新（2026-06-08）— 后台四项强化：摄取可见性 / 抓取合规 / 提取质量 / 人工复核

围绕"AI+工具抓取整理、人工审核"原则，分四个可独立验证的阶段推进：

1. **摄取可见性**：`SourceDocument` 新增 `document_kind` 列；`/admin/documents` 增加
   类型/处理/附件列与状态快捷过滤（全部/待提取/待OCR/失败/需登录），待 OCR 列表支持
   「批量重新抓取」；任务详情文档表加「类型」列。
2. **抓取合规与稳健性**：`crawler/robots.py` 提供 `RobotsChecker`（按 origin 缓存
   robots.txt，fail-open）与 `DomainRateLimiter`（按域最小间隔）；接入 `CrawlJobRunner`：
   每次抓取前限速，robots 禁止则标记 blocked 跳过；`reset_stale_jobs` 在启动时重置
   残留 running 作业/任务。`RESPECT_ROBOTS` 开关。
3. **提取质量**：`_link_method_to_section` 改为优先用候选自身的 book_code/chapter_title/
   section_title 精确定位小节（高置信度），子串匹配仅作兜底且最多链接 3 个；证据/匹配
   置信度参数化（`EVIDENCE_DEFAULT_CONFIDENCE` / `EXTRACTION_MATCH_CONFIDENCE`）。
4. **人工复核界面**：新增候选详情页 `/admin/review/candidates/<id>`，展示方法字段、证据
   片段、源文档 Markdown 预览、调和决策；支持编辑（标题/类型/摘要/步骤/适用题型/误区）
   并同步更新由该候选生成的 canonical 方法，写入 `ManualEditLog`。

新增单测：`test_detect`（11）、`test_convert`（4）、`test_robots`（6）、
`test_extract_mapping`（2）、`test_review_edit`（2），均不依赖 markitdown/scrapling。

## 此前更新（2026-06-08）— 文档摄取层：类型识别 / markitdown / 附件 / Azure OCR

按"AI+工具抓取整理、人工审核"原则，强化 Phase 1 之后、Phase 2 之前的摄取层
（详见 [ingestion.md](ingestion.md)）：

- **文档类型识别**（`parsers/detect.py`）：magic 字节 → Content-Type → 扩展名 三层
  判断，对 PDF 再用 PyMuPDF 探测文字层，区分数字版/扫描版（OCR 成本开关）。
- **统一转换层**（`parsers/convert.py`）：HTML→trafilatura、数字版 PDF→PyMuPDF、
  Office(docx/pptx/xlsx)→markitdown、扫描件/图片→markitdown+Azure 文档智能；输出
  统一为 Markdown 存 `.data/text/<checksum>.md`。markitdown 懒加载，未安装只影响
  Office/扫描件路径。
- **附件下载**（`parsers/attachments.py`）：发现阶段识别 PDF/Office 附件并入队；深度
  抓取时同域附件不受路径前缀约束（`DOWNLOAD_ATTACHMENTS` 开关），Agent 发现里附件
  链接加分。
- **新增 `PipelineStatus.needs_ocr`**：扫描件/图片在未配置 Azure 时标记"待 OCR"，
  不中断流程；`/admin/documents` 可对其「重新抓取」。
- **配置**：`AZURE_DOC_INTEL_ENDPOINT/KEY`、`DOWNLOAD_ATTACHMENTS`；OCR 依赖以
  `pip install -e ".[ocr]"` 可选安装。
- **单测**：`tests/test_detect.py`（11 例，纯逻辑，不依赖网络/markitdown）。

> 环境提示：完整流水线需 `pip install -e ".[dev]"`（含 markitdown 与 scrapling）。
> 当前开发机缺这些重依赖，故只有不依赖它们的单测可本地跑通；类型识别/附件识别
> 已验证，Office/OCR 转换路径需装好依赖后验证。

## 此前更新（2026-06-08）— 死代码清理 / 文档中文化 / AI 文案修正

在「导航重组」之后，针对设计梳理反馈做了三类整改：

- **删除重复与死代码**：
  - 删除 `mathscout/worker.py`（Celery 任务模块）——真实运行流程走 FastAPI
    `BackgroundTasks`，该模块从未被接通，仅 README 提到。
  - 删除 `agents/orchestrator.py` 中重复的 `SourceDiscoveryAgent`（平凡版，仅
    worker.py 引用）与 `ReconciliationAgent`（仅 worker.py 引用）；保留实际被
    `admin/routes.py` 使用的 `AIOrchestratorAgent`。真正在用的链接发现器是
    `agents/source_discovery.py` 里的同名类。
  - 精简 `runtime.py`：删除从未被引用的 `FetchObservation` /
    `DiscoveryObservation` / `ExtractionObservation` / `ReconciliationObservation` /
    `MonitorObservation` 五个子类，以及未接通的 `normalize_task_result()` 全家；
    保留 `review.py` 实际使用的 `RuntimeStatus` / `RuntimeObservation` /
    `ReviewObservation`。
  - 移除随之失去消费者的依赖：`pyproject.toml` 删去 `celery` / `redis` / `typer`
    （CLI 用 argparse，未用 typer）；`config.py` 删去 `redis_url`；
    `docker-compose.yml` 删去 `redis` 容器。
- **文档中文化**：`README.md` 与 `docs/` 全部翻译为中文（`CLAUDE.md` 作为 Claude
  Code 的工具约定文件保留英文）。README 与 architecture 的技术栈描述改为与实际
  一致（Scrapling + BackgroundTasks + SQLite，而非此前文案里的 httpx/Playwright/
  Celery/Redis）。`architecture.md` 顶部新增「实现状态对照表」，各节用
  ✅/🚧/📋 标注实现状态。
- **修正夸大 AI 的文案**：把"AI 会规划/AI 自动发现链接"等措辞改实——当前编排与
  链接打分是**规则**逻辑，AI 仅用于 Phase 2 抽取。涉及 `agent.html` 引导语与复选框
  标签、`routes.py` 的 `_interpret_command`，以及 `AIOrchestratorAgent` 的 docstring。

## 此前更新（2026-06-08）— 后台导航重组

针对「后台界面交互逻辑混乱」的反馈，按三阶段流水线重新组织了 admin 导航与入口：

- **合并重复的 AI 指令入口**：`/admin/command`（结构化表单 + 指令/决策记录表格，
  通过 `AIOrchestratorAgent` 完整编排创建爬取任务）与 `/admin/agent`（聊天式
  UI，但模板引用的 `messages` / `jobs` 字段与路由实际返回的 `commands` /
  `decisions` 不匹配，初始页面与轮询接口均无法正常渲染——是个半成品/已损坏
  页面）功能高度重叠。删除了损坏的聊天界面路由（`agent_console` 旧版、
  `agent_messages`、`submit_agent_message`）与模板，将原 `/admin/command`
  路由与模板重命名为 `/admin/agent`，统一为「智能爬取 (Agent)」单一入口，
  归入 Phase 1。
- **顶部导航改为按阶段分组的二级结构**（`_header.html`）：一级导航为
  控制台 / Phase 1·爬取 / Phase 2·提取 / Phase 3·复核入库；二级子导航按
  所属阶段列出具体页面——爬取任务 / 智能爬取(Agent) / 来源站点 归入 Phase 1，
  已抓文档归入 Phase 2，复核队列 / 方法库 / 知识库 / 决策记录 / 变更记录
  归入 Phase 3——并根据当前路径前缀自动高亮所属阶段与子页面（含任务详情页
  这类带动态 ID 的路径）。
- **清理各模板重复/冲突的 `header`/`nav`/`.logo` 样式**：此前多数模板各自
  定义了一份不含 `.admin-brand`/`.admin-page-title`/`.admin-nav` 的通用
  `header{}` 规则，导致 `_header.html` 渲染出的导航在不同页面上样式不一致
  （部分页面的导航链接完全没有激活态高亮）；现统一改为引用
  `_shared_styles.html` 中的 `.admin-header`/`.admin-nav`/`.admin-subnav`，
  并新增二级子导航的样式定义。

已起本地开发服务器逐页验证全部 10 个后台路径（控制台、智能爬取、爬取任务、
任务详情、已抓文档、复核队列、方法库、知识库、来源站点、决策记录、变更记录）
均正常渲染（HTTP 200），导航分组归属与激活态高亮均符合预期；旧路径
`/admin/command` 已确认返回 404（已整体迁移，无需兼容重定向，因为是纯内部
后台工具且无外部书签依赖）。同时同步更新了 `CLAUDE.md` 中的页面路径文档。

## 此前更新（2026-06-07）

针对此前移植但未接通的功能与流水线缺口，完成并验证了以下三项开发：

- **复核操作接入 `/admin/review`**：原页面仍渲染只读的 `list.html`，`ReviewService`
  与 `review.html` 早已存在但从未连通。现已重写路由，渲染新模板并新增两个 POST
  路由（`/admin/review/candidates/{id}/{action}`、`/admin/review/items/{id}/{action}`），
  对接 `ReviewService.apply_candidate_action` / `apply_review_item_action`，
  实测「需编辑」操作可正确更新 `review_status` 并写入 `ManualEditLog`。
- **`not_before` 指数退避重试调度**：`CrawlTask.not_before` 列此前从未被读写。
  现已在 `CrawlJobRunner` 中接入：失败任务按 `30s * 2 ** (retries - 1)` 计算下次
  可重试时间并写入该列；调度循环优先挑选到期任务，对尚未到期的计划任务等待
  （上限 30 秒）后继续轮询，而非直接判定作业终态；达到 `max_retries`（默认 3）
  后任务保持失败终态。已用不可达 URL 实测验证：第 1 次失败后 30 秒重试，
  第 2 次失败后 60 秒重试，与公式完全吻合。
- **失败/需登录文档的重新抓取按钮**：此前没有任何针对 `pipeline_status =
  failed / login_required` 文档的重试入口（仅有一个未使用的展示文案占位
  `"retry_task": "重试任务"`）。现已在 `/admin/documents` 列表中为符合条件的
  文档新增「重新抓取」按钮，提交后通过 `CrawlJobRunner.create_job` 创建一个
  以该文档 URL 为种子的新抓取作业并立即在后台执行。同时为共享的 `list.html` /
  `_list_response` 增加了可选的按行操作列（`actions_enabled`），不影响其余
  仍使用旧版只读列表的页面。

详见 [first-version-pipeline.md](first-version-pipeline.md) 中「失败重试机制」
「失败文档重新抓取」「复核操作」三节。

## 当前可用状态

MathScout 已有一个可运行的首版，聚焦于收集教师解题方法，并把它们存储在教材结构
与知识点之下。

已实现：

- 通过 `.env` 的 SQLite 优先本地配置
- 可选的 DeepSeek / OpenAI 兼容抽取
- 从 `.template` 导入教材模板
- 来源站点种子写入
- 基于数据库的后台控制台计数
- 由教材/章/节/知识点表支撑的后台知识浏览页
- 由来源/爬取作业/文档/复核/变更/指令/方法等表支撑的后台列表页
- 单 URL 爬取
- 持久化、数据库支撑的爬取作业
- 通过作业状态实现的 暂停/续跑 行为
- HTML / PDF 解析
- 来源文档与证据存储
- AI 或规则的方法候选抽取
- canonical 教学方法创建
- 教师/来源方法变体创建
- 基础的"方法→知识点""方法→小节"推断
- 调和决策审计记录
- 复核队列操作按钮（通过 / 需编辑 / 拒绝），接入 `ReviewService` 并写入 `ManualEditLog`
- 失败任务指数退避重试调度（`CrawlTask.not_before`）
- 失败 / 需登录文档的「重新抓取」入口（`/admin/documents`）
- 从种子页发现链接（`discover_links=true` 深度抓取）
- 文档类型识别（magic / Content-Type / 扩展名 + PDF 文字层探测，区分数字版/扫描版）
- 统一转换层：HTML→trafilatura、数字版 PDF→PyMuPDF、Office(docx/pptx/xlsx)→markitdown，
  输出 Markdown
- 附件（课件/教案/学案）发现与下载，并接入转换流水线
- 扫描件/图片标记 `needs_ocr`；Azure 文档智能 OCR 作为配置开关（`.[ocr]` 可选依赖）
- 后台导航按三阶段分组的二级结构（`/admin/agent` 统一 AI 指令入口，
  归并自此前重复且部分损坏的 `/admin/command` + 聊天式 `/admin/agent`）

尚未实现：

- canonical 方法/变体的独立编辑表单与合并/拆分（候选复核详情已可编辑并同步方法）
- 更多后台详情页与检索/过滤（候选复核详情页已实现）
- 超出抽取之外的完整 LLM 调和
- Playwright 登录 Cookie 流程
- 用 Alembic 做 Postgres 迁移
- 向量检索 / pgvector
- 并发 worker 编排
- 跨阶段统一的结果格式：目前 `jobs.py` / `crawl.py` / `extract.py` 各自维护 result
  格式，仅 `review.py` 用 `ReviewObservation` 返回统一结果，尚未推广到其他阶段
  （`runtime.py` 中未接通的 `normalize_task_result()` 与各 `*Observation` 子类已删除）
- 来源策略的自动调整（如"连续 N 篇无新增就换源"）尚未实现

## 本地运行

需要 Python 3.11 或更高版本（已用 3.14.5 冒烟测试）。

```powershell
cd C:\Users\duyin\Desktop\MathScout
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
mathscout init-db
mathscout import-template
mathscout seed-sources
uvicorn mathscout.main:app --reload
```

后台 UI：

```text
http://127.0.0.1:8000/admin
```

后台 UI 与 CLI 使用相同的 `DATABASE_URL`。在默认 SQLite 配置下，初始化后控制台
应显示导入的模板数据：

- 知识点：417（canonical；425 条原始去重后，8 个跨小节/跨册重复各合并为一条）
- 来源站点：3

知识库页面会显示导入模板中的 1 个教材系列、6 个册、34 章、127 节、417 个 canonical
知识点（425 条小节覆盖链接）、16 项学生能力。

## 交接说明

`.env` 与 `.data/` 仅本地存在，不入库。在新环境中，把 `.env.example` 复制为 `.env`，
手动补上私有 API Key，然后运行：

```powershell
mathscout init-db
mathscout import-template
mathscout seed-sources
```

不要指望本机的 SQLite 数据库在克隆后仍存在；模板导入会重建基线教材数据。

## DeepSeek

编辑 `.env`：

```text
AI_PROVIDER=deepseek
DEEPSEEK_API_KEY=你的_deepseek_key
OPENAI_COMPATIBLE_BASE_URL=https://api.deepseek.com
OPENAI_COMPATIBLE_MODEL=deepseek-chat
```

运行：

```powershell
mathscout crawl-url "https://example.com/public-math-teaching-page" --extractor auto
```

若 `AI_PROVIDER=rule`，或 `auto` 模式下没有 API Key，爬虫会使用本地规则抽取器。

## 持久化作业

```powershell
mathscout create-job --name "teacher-pages" --url "https://example.com/a" --url "https://example.com/b"
mathscout run-job "<job_id>" --extractor auto
mathscout stop-job "<job_id>"
mathscout job-status "<job_id>"
```

`stop-job` 把 `paused` 写入数据库。`run-job` 在每个 URL 之间检查状态，因此已完成的
页面会保留，剩余任务停在 pending。

## 已做的验证

以下命令在本地 `.venv` 中成功运行：

```powershell
ruff check mathscout tests
pytest
```

SQLite 冒烟测试也通过：

- 建表
- 导入模板
- 创建爬取作业
- 对 `https://example.com` 运行作业
- 查询作业状态

## 建议的后续工作

1. 为教材结构与爬取产出增加后台详情页、过滤与检索。
2. 为 `TeachingMethod`、`TeachingMethodVariant` 及映射增加人工编辑表单。
3. 从种子来源页增加链接发现（已部分实现，可继续完善打分规则）。
4. （已完成）`RobotsChecker` 与按域限速已接入 `CrawlJobRunner`；后续可加按域并发与
   每域自定义延迟/配额。
5. 增加 Playwright 抓取器与登录受限来源的 Cookie 配置存储。
6. 用已有候选表，把规则调和替换为 AI 辅助调和。
7. Phase 2（提取）目前在二级导航中只挂了「已抓文档」一个页面——若后续需要
   单独查看「正在/待提取」批次历史或抽取日志，可以为 Phase 2 新增一个
   专属的提取记录页面，而不是只靠 `/admin/documents` 的 `pipeline_status` 列。
8. 二级子导航在窄屏（如移动端）下会换行堆叠，尚未做折叠/汉堡菜单适配；
   如果后台需要在小屏幕上使用，建议补充响应式收纳。

## 待确认事项（Open Questions）

- **`/admin/command` 旧路径是否需要兼容重定向**：此前直接将其迁移为
  `/admin/agent`（确认无外部书签/脚本依赖该路径，纯内部工具）。如果发现
  有自动化脚本或文档外链仍指向 `/admin/command`，需要补一条
  `RedirectResponse("/admin/agent")`。
- **「智能爬取 (Agent)」这个二级导航命名是否合适**：用于承载原
  `/admin/command` 的自然语言指令编排功能，如果团队内部已有更通用的叫法
  （如「AI 编排」「指令中心」），可以再调整 `_header.html` 中的 label 文案。
