# Crawl Policy

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
