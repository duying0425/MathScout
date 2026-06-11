"""Phase 2 统一抽取：一次 extract_document 同时产出上层（题目）+ 下层（教学方法）。

验证"管线优先级"修正——上层事实为主、技巧/方法仍作为下层一并抽取。
知识点为 AI-only，rule 模式下应为 0（不报错、不阻断）。
"""

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from mathscout.db.base import Base
from mathscout.db.models import (
    PipelineStatus,
    Problem,
    SourceDocument,
    TeachingMethod,
)
from mathscout.pipeline.extract import ExtractPipeline


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


SAMPLE = (
    "例1 计算 12+8 的值。\n"
    "解：原式 = 20。\n"
    "答案：20\n"
    "解题技巧：凑十法可以把 12+8 凑成整十再口算，避免进位出错。\n"
)


def test_extract_document_runs_upper_and_lower(tmp_path):
    session = _session()
    text_file = tmp_path / "doc.md"
    text_file.write_text(SAMPLE, encoding="utf-8")
    document = SourceDocument(
        url="https://example.com/lesson",
        text_path=str(text_file),
        pipeline_status=PipelineStatus.crawled,
    )
    session.add(document)
    session.flush()

    result = ExtractPipeline(session, extractor_mode="rule").extract_document(document)

    # 上层（题目）为主——一次抽取就产出题目
    assert result["problems"] >= 1
    assert result["solutions"] >= 1
    # 下层（技巧/方法）仍一并抽取
    assert result["methods"] >= 1
    # 知识点为 AI-only，rule 模式跳过且不报错
    assert result["knowledge_points"] == 0

    assert session.scalar(select(func.count()).select_from(Problem)) >= 1
    assert session.scalar(select(func.count()).select_from(TeachingMethod)) >= 1
    assert document.pipeline_status == PipelineStatus.extracted
