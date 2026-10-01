# Collector Bridge and Cover Letters

## Recommended source architecture

JobIntel now separates **collection** from **career intelligence**.

```text
Public APIs / authorized ATS feeds / approved external collector
                         ↓
                  normalized job JSON
                         ↓
                      JobIntel
                         ↓
                    PostgreSQL
                         ↓
              CV filtering + matching
                         ↓
        Job Market / applications / cover letters
```

This keeps browser automation out of the core application and makes every source replaceable.

## Direct employer ATS collectors

The Settings page can configure employer career sites backed by:

- **Lever (global)**
- **Lever (EU)**
- **SmartRecruiters**
- **Ashby**

You need the employer's public site/company identifier.

Examples of provider values:

```text
lever
lever-eu
smartrecruiters
ashby
```

When **Refresh Current Jobs** runs, JobIntel retrieves public postings for each configured target, keeps Germany/remote-EU technical roles, normalizes the job descriptions, extracts skills, and stores them in the same `live_jobs` table.

Lever exposes published employer postings, SmartRecruiters exposes public postings for configured companies, and Ashby exposes currently published jobs through its public Job Postings API. Use source-specific terms and rate limits.

Official documentation:
- https://github.com/lever/postings-api
- https://developers.smartrecruiters.com/docs/posting-api
- https://developers.ashbyhq.com/docs/public-job-posting-api

## Existing Playwright collector

If you already have a Playwright collector, keep it as a separate process and send its output into:

```http
POST /api/jobs/bulk-import
Authorization: Bearer <JobIntel session token>
Content-Type: application/json
```

Payload:

```json
{
  "jobs": [
    {
      "source": "Authorized External Collector",
      "title": "Backend Engineer",
      "company": "Example GmbH",
      "location": "Berlin, Germany",
      "url": "https://example.com/job/123",
      "description": "Full job description...",
      "remote": false
    }
  ]
}
```

The endpoint is idempotent for the same source + URL/title/company combination and updates an existing imported row instead of intentionally creating a duplicate.

For XING/StepStone, do not make automated collection part of the default JobIntel runtime unless you have permission/authorized access under the applicable platform terms. The bridge is deliberately source-agnostic so authorized collectors can be integrated without changing the core application.

## Cover letter workflow

Every job card now has:

```text
Apply on source
Create cover letter
Track application
```

**Create cover letter** uses:

- the logged-in profile,
- the latest uploaded CV,
- the exact stored job description,
- matched skills,
- missing skills.

If local Ollama is enabled and reachable, it generates a tailored letter under a strict prompt that prohibits invented experience. Otherwise JobIntel produces a deterministic CV-grounded template.

The result is downloaded as a `.docx` file and can be attached on the employer's application page.
