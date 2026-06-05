# Initial Source Notes

Last updated: 2026-06-05.

Checked on 2026-06-04.

Implementation roadmap: [Development Roadmap](development-roadmap.md).

## Official Baseline Sources

- 教育部办公厅关于印发《2024年义务教育国家课程教学用书目录（根据2022年版课程标准修订）》的通知  
  https://hudong.moe.gov.cn/srcsite/A26/s8001/202408/t20240805_1144254.html

- 义务教育数学课程标准（2022年版）PDF  
  https://www.moe.gov.cn/srcsite/A26/s8001/202204/W020220510531636118932.pdf

- 国家中小学智慧教育平台  
  https://basic.smartedu.cn

- 基础教育精品课平台资料  
  https://jpk.basic.smartedu.cn

## Design Implications

- Textbook rollout is time-sensitive. The app should store edition labels and
  regional adoption records with validity periods and evidence links.
- Regional usage should come from provincial/city/district education-bureau
  notices where possible, not from unsourced "教材版本地区表" posts.
- Public teaching resources can seed extraction, but canonical records should
  retain source provenance and review status.

## Current Source Strategy

- Official and public education sources remain the preferred seed set.
- The Agent Console can accept direct URLs in the user goal; manual URLs take
  priority over enabled default source sites.
- `SourceDiscoveryAgent` should select child links from fetched page candidates;
  it must not invent URLs.
- Public pages with normal login navigation should not be treated as blocked
  login pages. Protected-page prompts, access restrictions, and HTTP failures
  should stop before extraction and create structured observations.
- Login-gated sources require review and later user-provided cookie profiles.
  MathScout must not bypass captchas, paywalls, or access controls.
- Commercial or full-text copyrighted resources should be reviewed before their
  extracted summaries affect canonical records.

## Source Work Still Needed

- Add source detail pages with domain policy, crawl delay, robots status, and
  recent yield.
- Add source quality metrics from `quality_check` tasks.
- Add blocked-login/cookie-profile management for authorized domains.
- Add periodic source review so low-yield sources can be paused or reprioritized.
