from __future__ import annotations

import json
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from mathscout.db.models import (
    Book,
    Chapter,
    KnowledgePoint,
    Section,
    StudentSkill,
    TextbookSeries,
)
from mathscout.utils.text import normalize_semantic_key


def import_template_dir(session: Session, template_dir: Path) -> dict[str, int]:
    files = sorted(template_dir.glob("G*.json"))
    stats = {
        "files": 0,
        "series": 0,
        "books": 0,
        "chapters": 0,
        "sections": 0,
        "skills": 0,
        "knowledge_points": 0,
    }
    for file in files:
        data = json.loads(file.read_text(encoding="utf-8"))
        stats["files"] += 1
        stats = _import_semester(session, data, stats)
    session.commit()
    return stats


def _import_semester(session: Session, data: dict, stats: dict[str, int]) -> dict[str, int]:
    meta = data["meta"]
    version_info = meta["textbook_version_info"]
    series_name = version_info["textbook_series"]
    series = session.scalar(select(TextbookSeries).where(TextbookSeries.name == series_name))
    if series is None:
        series = TextbookSeries(
            name=series_name,
            publisher=_guess_publisher(series_name),
            school_system=_guess_school_system(series_name),
            curriculum_standard_basis=version_info.get("curriculum_standard_basis"),
            notes=version_info.get("note"),
        )
        session.add(series)
        session.flush()
        stats["series"] += 1

    for skill in data.get("shared_skill_catalog", []):
        existing_skill = session.scalar(
            select(StudentSkill).where(StudentSkill.skill_code == skill["skill_id"])
        )
        if existing_skill is None:
            session.add(
                StudentSkill(
                    skill_code=skill["skill_id"],
                    name=skill["name"],
                    description=skill.get("description"),
                )
            )
            stats["skills"] += 1

    semester = data["semester"]
    book_code = semester["semester_id"]
    book = session.scalar(
        select(Book).where(Book.series_id == series.id, Book.book_code == book_code)
    )
    if book is None:
        book = Book(
            series_id=series.id,
            book_code=book_code,
            grade=_grade_from_book_code(book_code),
            semester=_semester_from_book_code(book_code),
            label=semester["name"],
            edition_label=version_info.get("edition_label"),
            confidence=0.95,
        )
        session.add(book)
        session.flush()
        stats["books"] += 1

    for chapter_index, chapter_data in enumerate(semester.get("chapters", []), start=1):
        chapter = session.scalar(
            select(Chapter).where(
                Chapter.book_id == book.id,
                Chapter.chapter_code == chapter_data["chapter_id"],
            )
        )
        if chapter is None:
            chapter = Chapter(
                book_id=book.id,
                chapter_code=chapter_data["chapter_id"],
                title=chapter_data["title"],
                chapter_goal=chapter_data.get("chapter_goal"),
                position=chapter_index,
            )
            session.add(chapter)
            session.flush()
            stats["chapters"] += 1

        for section_index, section_data in enumerate(chapter_data.get("sections", []), start=1):
            section = session.scalar(
                select(Section).where(
                    Section.chapter_id == chapter.id,
                    Section.section_code == section_data["section_id"],
                )
            )
            if section is None:
                section = Section(
                    chapter_id=chapter.id,
                    section_code=section_data["section_id"],
                    title=section_data["title"],
                    position=section_index,
                )
                session.add(section)
                session.flush()
                stats["sections"] += 1

            for point in section_data.get("knowledge_points", []):
                semantic_key = normalize_semantic_key(
                    f"{series.name}:{book.book_code}:{section.section_code}:{point}"
                )
                existing_point = session.scalar(
                    select(KnowledgePoint).where(
                        KnowledgePoint.section_id == section.id,
                        KnowledgePoint.semantic_key == semantic_key,
                    )
                )
                if existing_point is None:
                    session.add(
                        KnowledgePoint(
                            section_id=section.id,
                            title=point,
                            description=None,
                            semantic_key=semantic_key,
                            source_type="template",
                            confidence=0.9,
                        )
                    )
                    stats["knowledge_points"] += 1
    return stats


def _guess_publisher(series_name: str) -> str | None:
    if "北师大" in series_name:
        return "北京师范大学出版社"
    if "人教" in series_name:
        return "人民教育出版社"
    return None


def _guess_school_system(series_name: str) -> str | None:
    if "六三制" in series_name:
        return "六三制"
    if "五四制" in series_name:
        return "五四制"
    return None


def _grade_from_book_code(book_code: str) -> int:
    match = re.match(r"G(\d+)", book_code)
    if not match:
        return 0
    return int(match.group(1))


def _semester_from_book_code(book_code: str) -> str:
    return "上册" if book_code.endswith("A") else "下册"
