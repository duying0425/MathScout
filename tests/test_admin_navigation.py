from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from mathscout.admin.routes import _extract_urls
from mathscout.db.base import Base
from mathscout.db.models import AccessLevel, CrawlJob, NaturalLanguageCommand, SourceSite
from mathscout.db.session import get_session
from mathscout.main import create_app


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _client(session_factory=None) -> TestClient:
    session_factory = session_factory or _session_factory()
    app = create_app()

    def override_session():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    return TestClient(app)


def test_admin_pages_share_global_navigation() -> None:
    with _client() as client:
        for path in ["/admin", "/admin/agent", "/admin/crawl-jobs", "/admin/review"]:
            response = client.get(path)
            html = response.text

            assert response.status_code == 200
            assert 'class="admin-header"' in html
            assert 'href="/admin/agent">Agent</a>' in html
            assert 'href="/admin/crawl-jobs">任务</a>' in html
            assert 'href="/admin/review">复核</a>' in html
            assert 'href="/admin/documents">文档</a>' in html
            assert 'href="/admin/changes">变更</a>' in html


def test_crawl_job_list_keeps_page_actions_out_of_global_header() -> None:
    with _client() as client:
        response = client.get("/admin/crawl-jobs")

    assert response.status_code == 200
    assert "新建 AI 指令" not in response.text
    assert "后台首页" not in response.text


def test_agent_url_extraction_trims_attached_chinese_instruction_text() -> None:
    text = (
        "\u8bf7\u5e2e\u6211\u6293\u53d6"
        "http://www.example.com/test"
        "\u4e0b\u7684\u6570\u636e"
    )

    assert _extract_urls(text) == ["http://www.example.com/test"]


def test_agent_console_message_api_creates_command_and_job() -> None:
    session_factory = _session_factory()
    with session_factory() as session:
        session.add(
            SourceSite(
                name="Example",
                base_url="https://example.com",
                domain="example.com",
                category="teacher_resource",
                access_level=AccessLevel.public,
                enabled=True,
                crawl_delay_seconds=0,
            )
        )
        session.commit()

    with _client(session_factory) as client:
        page_response = client.get("/admin/agent")
        post_response = client.post(
            "/admin/agent/messages",
            data={
                "objective": "收集七年级有理数教师解题方法",
                "seed_urls": "",
                "extractor_mode": "rule",
                "max_seed_urls": "1",
                "discovery_max_links": "2",
                "discover_links": "true",
                "auto_start": "false",
            },
        )

    with session_factory() as session:
        commands = session.scalars(select(NaturalLanguageCommand)).all()
        jobs = session.scalars(select(CrawlJob)).all()

    assert page_response.status_code == 200
    assert "种子 URL" not in page_response.text
    assert "抽取模式" not in page_response.text
    assert "最大种子数" not in page_response.text
    assert "自动发现链接" not in page_response.text
    assert post_response.status_code == 200
    assert post_response.json()["ok"] is True
    assert len(commands) == 1
    assert len(jobs) == 1
    assert post_response.json()["messages"]
