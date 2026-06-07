from dataclasses import dataclass
from enum import StrEnum


class SourceCategory(StrEnum):
    official = "official"
    publisher = "publisher"
    teacher_resource = "teacher_resource"
    regional_bureau = "regional_bureau"
    unknown = "unknown"


@dataclass(frozen=True)
class SeedSource:
    name: str
    base_url: str
    category: SourceCategory
    notes: str = ""


DEFAULT_SEED_SOURCES: tuple[SeedSource, ...] = (
    SeedSource(
        name="国家中小学智慧教育平台",
        base_url="https://basic.smartedu.cn",
        category=SourceCategory.official,
        notes="优先采集公开课程和教材元数据；登录资源需用户授权 cookie。",
    ),
    SeedSource(
        name="教育部政府门户网站",
        base_url="https://www.moe.gov.cn",
        category=SourceCategory.official,
        notes="课程标准、教学用书目录和教材政策。",
    ),
    SeedSource(
        name="基础教育精品课",
        base_url="https://jpk.basic.smartedu.cn",
        category=SourceCategory.official,
        notes="公开精品课、微课、教学设计和任务单元数据。",
    ),
)
