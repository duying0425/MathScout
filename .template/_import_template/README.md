# 教材导入模板（Textbook Import Template）

把教材结构做成本目录这样的 JSON，再用 CLI 导入数据库。解析逻辑见
[`mathscout/importers/template.py`](../../mathscout/importers/template.py)，
字段与库表的对应见 [`docs/data-model.md`](../../docs/data-model.md)。

## 一、怎么用

1. 复制 `G7A_示例册.json`，按真实教材填写（**一个文件 = 一册/一个学期**）。
2. 文件名用 `G*.json`（导入器只扫 `G` 开头的 json），建议 `G<年级><A|B>_<册名>.json`。
3. 导入：

   ```bash
   # 导入本模板目录
   .venv/Scripts/mathscout.exe import-template --template-dir .template/_import_template

   # 或放进你自己的目录再指向它
   .venv/Scripts/mathscout.exe import-template --template-dir 路径/到/你的目录
   ```

   不带 `--template-dir` 时用默认目录 `.template/beishida_math_json_v3_with_template`。

## 二、字段说明

| JSON 路径 | 必填 | 写入库表 / 字段 | 说明 |
|-----------|------|------------------|------|
| `meta.textbook_version_info.textbook_series` | ✅ | `textbook_series.name` | 版本族名，**系列去重键**。不同名 = 新建一套教材 |
| `meta.textbook_version_info.curriculum_standard_basis` | 否 | `textbook_series.curriculum_standard_basis` | 课程标准依据 |
| `meta.textbook_version_info.edition_label` | 否 | `books.edition_label` | 版次标签，如“2024秋版” |
| `meta.textbook_version_info.note` | 否 | `textbook_series.notes` | 版本备注 |
| `shared_skill_catalog[]` | 否 | `student_skills` | 全局能力表，按 `skill_id` 去重；`{skill_id,name,description}` |
| `semester.semester_id` | ✅ | `books.book_code` | 册编号，如 `G7A`；决定年级与上下册（见下） |
| `semester.name` | ✅ | `books.label` | 册名，如“七年级上册” |
| `semester.chapters[].chapter_id` | ✅ | `chapters.chapter_code` | 章编号，**章去重键**（建议带册前缀，如 `G7A-C1`） |
| `semester.chapters[].title` | ✅ | `chapters.title` | 章标题 |
| `semester.chapters[].chapter_goal` | 否 | `chapters.chapter_goal` | 章目标 |
| `…sections[].section_id` | ✅ | `sections.section_code` | 小节编号，**小节去重键**（如 `G7A-C1-S1`） |
| `…sections[].title` | ✅ | `sections.title` | 小节标题 |
| `…sections[].knowledge_points[]` | 否 | `knowledge_points` + `section_knowledge_point_links` | **字符串数组**；每个知识点按内容去重，并与本小节建“introduce”链接 |
| `…sections[].skill_refs[]` | — | （不导入） | 仅作标注，导入器当前不读取 |

`semester_id` 推导规则（[`template.py`](../../mathscout/importers/template.py)）：`G7A` → 年级 7、
`A` 结尾=上册 / `B` 结尾=下册；`publisher`、`school_system` 由系列名猜测
（含“北师大/人教”“六三制/五四制”）。

## 三、导入行为（重要）

- **幂等增量**：每层“不存在才建”——系列按名字、册按 `book_code`、章/节按各自 code、
  **知识点按内容（标题归一化）去重**。重复导入不会重复建。
- **知识点跨版本共享**：同一标题的知识点全库**只存一条**，被多个小节/版本以
  `section_knowledge_point_links` 关联（“教材是视图、知识点是事实”）。
- ⚠️ **只增不改不删**：已存在的记录**不更新字段**、**不删除**。改已有内容目前需直接动数据库。
