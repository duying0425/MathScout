# Crawl Policy

Last updated: 2026-06-05.

For the broader implementation plan, see
[Development Roadmap](development-roadmap.md).

MathScout should crawl slowly, visibly, and with provenance.

## Allowed by Default

- Public government pages and PDFs.
- Public school and teaching-research pages.
- Public publisher catalogue pages.
- User-uploaded documents that the user has rights to process.

## Requires Review

- Sites with login.
- Sites with unclear terms.
- Public pages that contain obvious commercial copyrighted resources.
- Video platforms and file-sharing sites.

## Not Supported

- Captcha bypass.
- Paywall bypass.
- DRM bypass.
- Credential sharing across users or domains.
- Republishing full copyrighted textbooks, teacher guides, paid course notes, or problem books.

## Fetch Rules

- Per-domain rate limit.
- Robots.txt check where applicable.
- Content hash deduplication.
- Store raw content separately from canonical extracted data.
- Track source URL, fetched time, parser version, extractor version, and review status.

## Runtime Enforcement

The DB-backed crawl job runner now executes deterministic fetch policy gates
before and after network fetching.

Implemented checks:

Before fetch:

- Only HTTP(S) URLs with a domain are executable.
- Registered source sites marked `enabled=false` are blocked and sent to review.
- Registered source sites marked `login_required` or `paid_or_restricted` are
  blocked and sent to review.
- Registered source sites honor robots.txt unless the job explicitly sets
  `respect_robots=false`.
- Registered source sites honor `crawl_delay_seconds` based on the latest
  fetched document for that site by deferring the task through
  `crawl_tasks.not_before`.

After fetch:

- HTTP 4xx/5xx responses stop before extraction and are recorded as fetch
  failures.
- Login-gated or access-restricted responses stop before extraction and create
  review-required observations.
- Clearly unsupported binary content types stop before extraction.
- Empty pages and short boilerplate/error pages stop before extraction.

Still pending:

- Cookie-profile based access for user-authorized login sources.

## Policy Work Still Needed

- Add Playwright/browser fetching only for user-authorized sources.
- Store cookie profiles by domain with expiration metadata and avoid
  cross-domain reuse.
- Add UI for blocked-login source review and cookie refresh.
- Add per-domain concurrency controls when an independent worker is introduced.
- Add source-yield metrics so low-value or noisy sources can be paused by
  deterministic stop conditions or reviewed Agent strategy changes.
- Add clearer copyright review states for pages that are public but obviously
  commercial, paid, or full-text copyrighted resources.
