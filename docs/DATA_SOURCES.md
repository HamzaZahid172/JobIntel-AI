# German Job Data Source Strategy

JobIntel is designed to expand German job-market coverage without making prohibited scraping a core dependency.

## Active sources

### Arbeitnow
Used through its public job-board API. JobIntel stores relevant technical jobs in PostgreSQL, normalizes descriptions and skills, and keeps the original source URL.

### Jobicy
Used through its public remote-jobs API with Germany filtering.

### Manual import
The Job Market page supports manual import of a job title, company, URL and description. This is the safe fallback for individual jobs found on platforms that do not provide us with authorized search-data access.

## XING

JobIntel does **not** automatically scrape XING.

XING's current general terms prohibit using mechanisms, software or scripts on XING websites except authorized interfaces/software. XING does provide developer/partner APIs, but its documented E-Recruiting Job API is primarily for contracted customers posting and managing their own job ads, not an unrestricted public job-search export.

Strategy:
1. Request/obtain authorized XING integration access if JobIntel ever becomes a supported partner/customer integration.
2. Until then, import individual XING jobs manually into JobIntel.
3. Preserve the XING URL as the source of truth and never republish whole listings publicly.

References:
- https://www.xing.com/legal/api/pages/terms_and_conditions/xing.html
- https://developer.xing.com/partners/job_integration/api_docs

## StepStone

JobIntel does **not** automatically scrape StepStone.

StepStone's applicant terms explicitly prohibit scraping or similar techniques to collect content for another purpose or republish/use it differently from the intended service.

Strategy:
1. Prefer authorized/partner access if StepStone offers a suitable agreement/API for this use case.
2. Until authorized, use the JobIntel manual-import workflow for jobs the user finds.
3. Store only what is needed for the user's private career analysis and preserve the original StepStone URL.

Reference:
- https://www.stepstone.de/Ueber-StepStone/legal-notes/general-terms-use/

## Recommended expansion for better Germany coverage

Instead of relying on XING/StepStone scraping, add adapters for employer career systems where public job feeds/endpoints are available, for example:

- Greenhouse
- Lever
- SmartRecruiters
- Teamtailor
- Workday public career pages where an allowed feed/interface is available
- direct company career-site feeds

The collector architecture should normalize every source to the same schema:

```text
source
source_id
title
company
location
remote
url
description
skills
job_types
posted_at
fetched_at
```

Then:

```text
authorized/public source
        ↓
source adapter
        ↓
normalize + deduplicate
        ↓
PostgreSQL
        ↓
CV-first filtering
        ↓
match engine
        ↓
dashboard / Job Market
```

## Refresh policy

Public external feeds should be refreshed conservatively, normally hourly. Manual imports are immediate. Source-specific terms and rate limits always take priority over JobIntel's default schedule.
