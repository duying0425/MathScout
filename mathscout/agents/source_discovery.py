from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from urllib.parse import urldefrag, urljoin, urlparse

from scrapling.fetchers import AsyncFetcher
from scrapling.parser import Adaptor

from mathscout.agents.base import AgentResult, AgentStatus
from mathscout.parsers.attachments import is_attachment_url

POSITIVE_KEYWORDS = {
    "初中": 8,
    "数学": 8,
    "七年级": 8,
    "八年级": 8,
    "九年级": 8,
    "北师大": 8,
    "有理数": 10,
    "一元一次方程": 10,
    "几何": 8,
    "函数": 8,
    "统计": 6,
    "解题": 12,
    "方法": 8,
    "技巧": 8,
    "例题": 8,
    "教学设计": 12,
    "教案": 10,
    "课件": 8,
    "公开课": 10,
    "精品课": 10,
    "微课": 8,
    "说课": 8,
    "教研": 8,
    "任务单": 7,
    "课程标准": 7,
    "教材": 6,
    "目录": 4,
    "lesson": 8,
    "course": 6,
    "resource": 5,
    "math": 6,
}

NEGATIVE_KEYWORDS = {
    "登录": -20,
    "注册": -18,
    "退出": -18,
    "login": -20,
    "logout": -20,
    "register": -18,
    "captcha": -20,
    "javascript": -20,
    "广告": -10,
    "首页": -2,
}

NON_MATH_SUBJECT_KEYWORDS = {
    "语文",
    "英语",
    "物理",
    "化学",
    "生物",
    "地理",
    "历史",
    "政治",
    "道德与法治",
    "科学",
    "音乐",
    "美术",
    "体育",
    "信息技术",
}

MATH_SIGNAL_KEYWORDS = {
    "数学",
    "math",
    "有理数",
    "方程",
    "几何",
    "函数",
    "统计",
    "代数",
    "不等式",
    "分式",
    "根式",
    "概率",
    "坐标",
    "三角形",
    "四边形",
    "多边形",
    "圆",
    "轴对称",
    "平移",
    "旋转",
    "相似",
}

SPECIFIC_RESOURCE_KEYWORDS = {
    "有理数",
    "方程",
    "几何",
    "函数",
    "统计",
    "不等式",
    "分式",
    "根式",
    "概率",
    "坐标",
    "三角形",
    "四边形",
    "多边形",
    "轴对称",
    "平移",
    "旋转",
    "相似",
    "解题",
    "方法",
    "技巧",
    "例题",
    "教学设计",
    "教案",
    "课件",
    "公开课",
    "精品课",
    "微课",
    "说课",
    "教研",
    "任务单",
    "学案",
    "练习",
    "试题",
    "试卷",
    "复习",
    "课堂",
    "易错",
    "讲法",
    "ppt",
    "pptx",
}

GENERIC_DIRECTORY_LABELS = {
    "初中数学",
    "数学",
    "初中",
    "七年级上册",
    "七年级下册",
    "八年级上册",
    "八年级下册",
    "九年级上册",
    "九年级下册",
    "七年级上册（新教材）",
    "七年级下册（新教材）",
    "八年级上册（新教材）",
    "八年级下册（新教材）",
    "九年级上册（新教材）",
    "九年级下册（新教材）",
}

STATIC_SUFFIXES = {
    ".css",
    ".js",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".svg",
    ".ico",
    ".webp",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".zip",
    ".rar",
    ".7z",
    ".mp4",
    ".mp3",
}

JUNIOR_MIDDLE_SIGNALS = {
    "初中",
    "七年级",
    "八年级",
    "九年级",
    "中考",
    "七上",
    "七下",
    "八上",
    "八下",
    "九上",
    "九下",
}

NON_JUNIOR_STAGE_SIGNALS = {
    "小学",
    "一年级",
    "二年级",
    "三年级",
    "四年级",
    "五年级",
    "六年级",
    "高中",
    "高一",
    "高二",
    "高三",
}


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str
    checks: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DiscoveredLink:
    url: str
    label: str
    score: float
    reasons: list[str]
    source_url: str
    policy: PolicyDecision

    def model_dump(self) -> dict[str, object]:
        return {
            "url": self.url,
            "label": self.label,
            "score": self.score,
            "reasons": self.reasons,
            "source_url": self.source_url,
            "policy": {
                "allowed": self.policy.allowed,
                "reason": self.policy.reason,
                "checks": self.policy.checks,
            },
        }


class PolicyGuardAgent:
    """对 AI 选择的链接执行确定性爬取策略检查。"""

    def allow_link(self, url: str, seed_url: str, allow_external: bool = False) -> PolicyDecision:
        parsed = urlparse(url)
        seed = urlparse(seed_url)
        checks = {
            "scheme": parsed.scheme,
            "domain": parsed.netloc,
            "seed_domain": seed.netloc,
            "same_domain": parsed.netloc == seed.netloc,
        }
        if parsed.scheme not in {"http", "https"}:
            return PolicyDecision(False, "拦截：非 HTTP(S) 链接", checks)
        if parsed.netloc == "":
            return PolicyDecision(False, "拦截：缺少域名", checks)
        if not allow_external and parsed.netloc != seed.netloc:
            return PolicyDecision(False, "拦截：跨域链接", checks)
        lowered = url.lower()
        if any(lowered.endswith(suffix) for suffix in STATIC_SUFFIXES):
            return PolicyDecision(False, "拦截：静态资源文件", checks)
        if any(keyword in lowered for keyword in ["login", "logout", "register", "captcha"]):
            return PolicyDecision(False, "拦截：登录、注册或验证码链接", checks)
        if any(keyword in url for keyword in ["登录", "注册", "验证码"]):
            return PolicyDecision(False, "拦截：登录、注册或验证码链接", checks)
        return PolicyDecision(True, "允许爬取", checks)


class SourceDiscoveryAgent:
    """从种子页发现候选链接，并按教学资源价值排序。"""

    def __init__(self, policy_guard: PolicyGuardAgent | None = None) -> None:
        self.policy_guard = policy_guard or PolicyGuardAgent()

    def run(
        self,
        seed_url: str,
        objective: str,
        max_links: int = 12,
        allow_external: bool = False,
    ) -> AgentResult:
        try:
            response = asyncio.run(
                AsyncFetcher.get(
                    seed_url,
                    impersonate="chrome",
                    stealthy_headers=True,
                    follow_redirects=True,
                    timeout=30,
                )
            )
            final_url = str(response.url)
            http_status = response.status
            needs_login = _looks_login_gated(response)

            if needs_login:
                return AgentResult(
                    status=AgentStatus.blocked,
                    payload={
                        "seed_url": seed_url,
                        "final_url": final_url,
                        "http_status": http_status,
                        "needs_login": True,
                        "selected_links": [],
                    },
                    error="种子页面疑似需要登录。",
                )

            links = self.discover_from_response(
                response=response,
                seed_url=final_url,
                objective=objective,
                max_links=max_links,
                allow_external=allow_external,
            )
            return AgentResult(
                status=AgentStatus.succeeded,
                payload={
                    "seed_url": seed_url,
                    "final_url": final_url,
                    "http_status": http_status,
                    "needs_login": False,
                    "selected_links": [link.model_dump() for link in links],
                    "selected_count": len(links),
                },
            )
        except Exception as exc:
            return AgentResult(
                status=AgentStatus.failed,
                payload={"seed_url": seed_url, "selected_links": []},
                error=str(exc),
            )

    def discover_from_response(
        self,
        response,
        seed_url: str,
        objective: str,
        max_links: int = 12,
        allow_external: bool = False,
    ) -> list[DiscoveredLink]:
        return self._extract_links(response, seed_url, objective, max_links, allow_external)

    def discover_from_html(
        self,
        html: str,
        seed_url: str,
        objective: str,
        max_links: int = 12,
        allow_external: bool = False,
    ) -> list[DiscoveredLink]:
        page = Adaptor(html, url=seed_url)
        return self._extract_links(page, seed_url, objective, max_links, allow_external)

    def _extract_links(
        self,
        page,
        seed_url: str,
        objective: str,
        max_links: int,
        allow_external: bool,
    ) -> list[DiscoveredLink]:
        seen: set[str] = set()
        links: list[DiscoveredLink] = []
        for anchor in page.css("a"):
            href = anchor.attrib.get("href")
            if not href:
                continue
            url = _normalize_url(urljoin(seed_url, href))
            if not url or url in seen:
                continue
            seen.add(url)
            label = " ".join((anchor.get_all_text(separator=" ") or "").split())
            policy = self.policy_guard.allow_link(
                url=url,
                seed_url=seed_url,
                allow_external=allow_external,
            )
            if not policy.allowed:
                continue
            score, reasons = score_link(url=url, label=label, objective=objective)
            if score <= 0:
                continue
            links.append(
                DiscoveredLink(
                    url=url,
                    label=label or url,
                    score=score,
                    reasons=reasons,
                    source_url=seed_url,
                    policy=policy,
                )
            )

        links.sort(key=lambda link: (-link.score, len(link.url), link.url))
        return links[:max_links]


def score_link(url: str, label: str, objective: str) -> tuple[float, list[str]]:
    text = f"{url} {label}".lower()
    original_text = f"{url} {label}"
    objective_terms = _objective_terms(objective)
    score = 0.0
    reasons: list[str] = []

    for keyword, weight in POSITIVE_KEYWORDS.items():
        haystack = text if keyword.isascii() else original_text
        if keyword.lower() in haystack:
            score += weight
            reasons.append(f"keyword:{keyword}")

    for keyword, weight in NEGATIVE_KEYWORDS.items():
        haystack = text if keyword.isascii() else original_text
        if keyword.lower() in haystack:
            score += weight
            reasons.append(f"negative:{keyword}")

    for term in objective_terms:
        if len(term) >= 2 and term in original_text:
            score += 6
            reasons.append(f"objective:{term}")

    objective_targets_junior = _objective_targets_junior_middle(objective)
    if objective_targets_junior and _contains_keyword(
        original_text,
        text,
        JUNIOR_MIDDLE_SIGNALS,
    ):
        score += 10
        reasons.append("objective_stage:初中")
    if objective_targets_junior and _contains_keyword(
        original_text,
        text,
        NON_JUNIOR_STAGE_SIGNALS,
    ):
        score -= 24
        reasons.append("negative:非初中学段")

    math_signal = _contains_keyword(original_text, text, MATH_SIGNAL_KEYWORDS)
    specific_signal = _contains_keyword(original_text, text, SPECIFIC_RESOURCE_KEYWORDS)
    objective_signal = any(reason.startswith("objective:") for reason in reasons)
    if _contains_keyword(original_text, text, NON_MATH_SUBJECT_KEYWORDS) and not math_signal:
        score -= 24
        reasons.append("negative:非数学学科")
    if not math_signal and not objective_signal:
        score -= 14
        reasons.append("negative:缺少数学信号")
    if _is_generic_directory_label(label) or (
        math_signal and not specific_signal and not objective_signal
    ):
        score -= 16
        reasons.append("negative:泛目录")

    parsed = urlparse(url)
    path = parsed.path.lower()
    if path.endswith(".pdf"):
        score += 5
        reasons.append("format:pdf")
    if is_attachment_url(url):
        # 课件/教案/学案等附件是高价值教学资源，适当加分。
        score += 8
        reasons.append("format:附件")
    if any(marker in path for marker in ["/lesson", "/course", "/resource", "/jiaoan"]):
        score += 4
        reasons.append("path:教学资源路径")
    if not math_signal and not objective_signal:
        score = min(score, -1.0)
    if _is_generic_directory_label(label):
        score = min(score, 0.0)

    if not reasons:
        reasons.append("低信号")
    return score, reasons


def _objective_terms(objective: str) -> list[str]:
    separators = " ，。；;,.!?！？、/\\|()（）[]【】"
    terms: list[str] = []
    current = []
    for char in objective:
        if char in separators:
            if current:
                terms.append("".join(current))
                current = []
            continue
        current.append(char)
    if current:
        terms.append("".join(current))
    return terms


def _objective_targets_junior_middle(objective: str) -> bool:
    lowered = objective.lower()
    if "junior" in lowered or "middle school" in lowered:
        return True
    return any(keyword in objective for keyword in JUNIOR_MIDDLE_SIGNALS)


def _contains_keyword(original_text: str, lowered_text: str, keywords: set[str]) -> bool:
    for keyword in keywords:
        haystack = lowered_text if keyword.isascii() else original_text
        if keyword.lower() in haystack:
            return True
    return False


def _is_generic_directory_label(label: str) -> bool:
    compact = "".join(label.split())
    if compact in GENERIC_DIRECTORY_LABELS:
        return True
    if compact.startswith("初中数学") and len(compact) <= len("初中数学") + 4:
        return True
    return False


def _normalize_url(url: str) -> str | None:
    url, _fragment = urldefrag(url.strip())
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme in {"mailto", "tel", "javascript"}:
        return None
    return url


def _looks_login_gated(response) -> bool:
    if response.status in {401, 403}:
        return True
    content_type = response.headers.get("Content-Type", "") or ""
    if "text" not in content_type:
        return False
    raw = response.body
    text = raw.decode(response.encoding or "utf-8", errors="ignore")
    markers = ("登录", "login", "captcha", "验证码")
    return any(marker in text[:5000].lower() for marker in markers)
