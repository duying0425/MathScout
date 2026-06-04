from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from mathscout.agents.source_discovery import PolicyGuardAgent, SourceDiscoveryAgent
from mathscout.db.base import Base
from mathscout.db.models import CrawlJob, CrawlStatus, CrawlTask
from mathscout.pipeline.jobs import CrawlJobRunner, _fallback_seed_link, _seed_crawl_link


def test_source_discovery_scores_teaching_links() -> None:
    html = """
    <html>
      <body>
        <a href="/lesson/qinianji/youlishu-jiaoxuesheji.html">七年级有理数教学设计</a>
        <a href="/static/logo.png">logo</a>
        <a href="/login">登录</a>
        <a href="https://other.example.com/math">外站数学</a>
        <a href="/news/general.html">学校新闻</a>
      </body>
    </html>
    """
    links = SourceDiscoveryAgent().discover_from_html(
        html=html,
        seed_url="https://example.com/index.html",
        objective="优先补充七年级上册有理数的教师解题方法",
        max_links=5,
    )

    assert [link.url for link in links] == [
        "https://example.com/lesson/qinianji/youlishu-jiaoxuesheji.html"
    ]
    assert links[0].score > 0
    assert "keyword:七年级" in links[0].reasons
    assert "keyword:教学设计" in links[0].reasons


def test_policy_guard_blocks_static_and_cross_domain_links() -> None:
    guard = PolicyGuardAgent()

    assert not guard.allow_link(
        "https://example.com/assets/app.js",
        "https://example.com",
    ).allowed
    assert not guard.allow_link(
        "https://other.example.com/lesson.html",
        "https://example.com",
    ).allowed
    assert guard.allow_link(
        "https://example.com/lesson.html",
        "https://example.com",
    ).allowed


def test_source_discovery_ignores_non_math_and_generic_catalog_links() -> None:
    html = """
    <html>
      <body>
        <a href="/mulu/2941.html">初中数学</a>
        <a href="/mulu/2.html">初中语文</a>
        <a href="/mulu/1756.html">初中英语</a>
        <a href="/course/unit6.html">Unit 6 Travelling around Asia 单元复习课件</a>
        <a href="/mulu/25210.html">6.2 解一元一次方程</a>
        <a href="/P/100.html">一元一次方程教学设计</a>
      </body>
    </html>
    """
    links = SourceDiscoveryAgent().discover_from_html(
        html=html,
        seed_url="https://example.com/index.html",
        objective="收集初中数学一元一次方程的教师解题方法",
        max_links=10,
    )

    urls = [link.url for link in links]
    assert "https://example.com/mulu/25210.html" in urls
    assert "https://example.com/P/100.html" in urls
    assert "https://example.com/mulu/2941.html" not in urls
    assert "https://example.com/mulu/2.html" not in urls
    assert "https://example.com/mulu/1756.html" not in urls
    assert "https://example.com/course/unit6.html" not in urls


def test_discovery_fallback_can_create_crawl_task_for_seed_url() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    with session_factory() as session:
        job = CrawlJob(
            name="test",
            status=CrawlStatus.running,
            source_filter={},
        )
        session.add(job)
        session.flush()
        source_task = CrawlTask(
            job_id=job.id,
            url="https://example.com/catalog",
            task_type="discover_links",
            status=CrawlStatus.succeeded,
        )
        session.add(source_task)
        session.flush()

        created = CrawlJobRunner(session)._create_crawl_tasks_from_discovery(
            job,
            source_task,
            [_fallback_seed_link(source_task.url)],
        )
        session.commit()

        tasks = session.scalars(
            select(CrawlTask).where(CrawlTask.job_id == job.id).order_by(CrawlTask.task_type)
        ).all()

    assert len(created) == 1
    assert created[0].url == "https://example.com/catalog"
    assert [task.task_type for task in tasks] == ["crawl_url", "discover_links"]


def test_discovery_can_create_seed_and_selected_crawl_tasks() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    with session_factory() as session:
        job = CrawlJob(
            name="test",
            status=CrawlStatus.running,
            source_filter={},
        )
        session.add(job)
        session.flush()
        source_task = CrawlTask(
            job_id=job.id,
            url="https://example.com/catalog",
            task_type="discover_links",
            status=CrawlStatus.succeeded,
        )
        session.add(source_task)
        session.flush()

        created = CrawlJobRunner(session)._create_crawl_tasks_from_discovery(
            job,
            source_task,
            [
                _seed_crawl_link(source_task.url),
                {
                    "url": "https://example.com/P/100.html",
                    "score": 20,
                    "reasons": ["keyword:教学设计"],
                },
            ],
        )
        session.commit()

        tasks = session.scalars(
            select(CrawlTask).where(CrawlTask.job_id == job.id).order_by(CrawlTask.url)
        ).all()

    assert len(created) == 2
    assert [(task.url, task.task_type) for task in tasks] == [
        ("https://example.com/P/100.html", "crawl_url"),
        ("https://example.com/catalog", "discover_links"),
        ("https://example.com/catalog", "crawl_url"),
    ]
