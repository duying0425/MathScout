# 文档摄取与转换（Ingestion & Conversion）

本文描述 Phase 1 抓取之后、Phase 2 抽取之前的**文档摄取层**：如何识别文档类型、
转成统一文本（Markdown）、处理扫描件/图片 OCR，以及如何把页面里的附件也抓回来。
目标是让"工具"把各种来源的原始内容整理成干净、结构化的文本，AI 抽取与人工复核
都建立在更好的输入之上。

## 总流程

```
Phase1 抓取(bytes)
  → 文档类型识别 detect.py
  → 统一转换 convert.py（按类型选最擅长的工具）
  → 写入 .data/text/<checksum>.md
  → pipeline_status = crawled / needs_ocr / failed / login_required
  → Phase2 AI 抽取
```

## 1. 文档类型识别（`mathscout/parsers/detect.py`）

抓取来的 URL 常缺少可靠扩展名，`Content-Type` 也可能笼统或错误。识别用三层确定性
策略，优先级从高到低：

1. **文件 magic 字节**：`%PDF`、OLE2（旧版 Office）、`PK\x03\x04`（OOXML/zip，
   再读 zip 内 `word/`、`ppt/`、`xl/` 顶层目录判断子类型）、各图片签名。
2. **`Content-Type` 头**。
3. **URL 扩展名**。

识别结果为 `DocumentKind`：`html`、`pdf_digital`、`pdf_scanned`、`word`、
`powerpoint`、`excel`、`image`、`text`、`archive`、`unknown`。

对 PDF 额外用 PyMuPDF 探测前几页是否有可抽取文字层，区分：

- **数字版 PDF**（有文字层）→ 直接抽文本，免费；
- **扫描版 PDF**（无文字层）→ 需 OCR（走 Azure，见下）。

这一步是**控制 OCR 成本的关键开关**：只有扫描件/图片才会触发付费的 Azure 调用。

## 2. 统一转换（`mathscout/parsers/convert.py`）

各格式用最擅长的工具，而非一刀切：

| 类型 | 转换器 | 说明 |
|------|--------|------|
| HTML | trafilatura | 去导航/广告噪声，抽正文 |
| 数字版 PDF | PyMuPDF | 快，已是依赖 |
| Word / PPT / Excel | **markitdown** | 转 Markdown，保留标题/表格/列表结构 |
| 扫描版 PDF / 图片 | **markitdown + Azure 文档智能** | OCR；未配置时标记 needs_ocr |
| 纯文本 / CSV / JSON | 直接读取 | — |
| archive / unknown | —— | 标记 failed（不支持）|

输出统一为 Markdown 文本，存到 `.data/text/<checksum>.md`，Phase 2 直接读取。
Markdown 比纯文本保留了更多结构，对 LLM 抽取教学方法更友好。

markitdown 采用**懒加载**：未安装时只影响 Office/扫描件路径，HTML 与数字版 PDF
不受影响，应用仍可正常运行。

## 3. 扫描件 / 图片 OCR（Azure 文档智能，可选）

扫描版 PDF 与图片经 markitdown 调用 **Azure 文档智能（Document Intelligence）**
做 OCR。这是付费服务，按配置启用：

```text
# .env
AZURE_DOC_INTEL_ENDPOINT=https://<resource>.cognitiveservices.azure.com/
AZURE_DOC_INTEL_KEY=<可选；填了用 AzureKeyCredential，否则用 Azure 默认凭据>
```

并安装 OCR 可选依赖：

```powershell
pip install -e ".[ocr]"
```

未配置 `AZURE_DOC_INTEL_ENDPOINT` 时，扫描件/图片的 `pipeline_status` 会被标记为
`needs_ocr`（后台"待 OCR"），流程不中断；配置好之后，可在 `/admin/documents`
对这些文档点「重新抓取」重跑。

> 成本提示：识别层已先用 PyMuPDF 区分数字版/扫描版 PDF，只有真正的扫描件/图片才
> 调用 Azure，避免对有文字层的 PDF 付费。

## 4. 附件下载（`mathscout/parsers/attachments.py`）

初中数学的教师方法常藏在页面链接出去的附件里（课件 PPT、教案 DOC、学案 PDF），
而非页面正文。摄取层在链接发现阶段识别附件链接并入队抓取：

- **附件扩展名**：`.pdf .doc .docx .ppt .pptx .xls .xlsx .csv .rtf .odt .odp .ods`。
- **深度抓取**（`jobs.py:_add_discovered_links`）：同域附件链接**不受路径前缀约束**
  （附件常在 `/uploads`、`/files` 等目录），由 `DOWNLOAD_ATTACHMENTS` 开关控制；
  普通页面链接仍只跟踪种子目录前缀下的链接，避免抓取整站。
- **Agent 发现**（`source_discovery.py:score_link`）：附件链接获得加分，让
  "有理数教案.pdf" 这类高价值资源排名靠前。

附件下载后与普通页面走同一条转换流水线——抓取器本就按字节存任意 URL，转换层据
类型选择 markitdown 等工具，因此附件的"识别 → 转换 → 抽取"是自动衔接的。

```text
# .env
DOWNLOAD_ATTACHMENTS=true
```

## 5. 数学内容（LaTeX / 图片 / TikZ）📋 规划

> 配合"四维知识图谱"重构的 **Phase C（题目 + 解答）**，见
> [knowledge-graph-redesign.md](knowledge-graph-redesign.md)。题目与解答含大量公式
> 与图形，是只抽散文式教学方法时不存在的新摄取需求。

约定：

- **公式 → LaTeX**：题干与解题步骤统一存为**含数学的 Markdown / LaTeX 文本**。
  - 来源已是 LaTeX/MathML（如部分题库、Office 公式）→ 规范化为 LaTeX。
  - 来源是图片中的公式 → 经 OCR / 多模态模型识别为 LaTeX。
- **图形 → 图片 + 可选 TikZ**：
  - 原图作为**可选附件**存 `.data/figures/...`，由 `figures.image_path` 记录。
  - **可选增强**：用 AI 把图片转成 **TikZ 源码**（`figures.tikz_code`，
    `origin=ai_generated`），便于无损缩放、版本化与再编辑。
  - TikZ 生成是**可选步骤，类比 OCR**：未启用 / 失败时只保留原图，**不阻断流程**。
- **成本开关**：与 OCR 一样，图片→TikZ 走付费/多模态通道时应有显式配置开关，
  仅对真正需要的题目图形触发。

数学内容的存储字段（`problems.stem`、`solutions.steps`、`figures.*`）定义见
[knowledge-graph-redesign.md §3](knowledge-graph-redesign.md)。

## 与"AI + 工具 + 人工审核"原则的关系

- **工具**（确定性）：抓取、类型识别、转换、附件发现——把杂乱来源整理成干净 Markdown。
- **AI**：Phase 2 在干净 Markdown 上抽取教师方法（DeepSeek）；扫描件/图片由 Azure
  文档智能识别。
- **人工审核**：Phase 3 复核队列不变——所有候选仍需人工确认才入库。

## 相关单元测试

- `tests/test_detect.py`：magic 字节、OOXML 子类型、Content-Type / 扩展名兜底、
  HTML 文本嗅探、附件链接识别。这些纯逻辑测试不依赖网络或 markitdown。
