# JobIntel AI Architecture

## 1. Product runtime

```text
Browser
   ↓
Nginx static frontend (HTML/CSS/JavaScript)
   ↓
FastAPI API
   ├── authentication/profile
   ├── CV parsing + ATS Readiness
   ├── source/collector orchestration
   ├── Match Layer
   ├── Application Preparation Layer
   ├── application CRM
   ├── cover-letter generation
   └── Career Assistant
   ↓
PostgreSQL
```

Ollama runs locally in Docker. JobIntel uses it when the configured model is ready and falls back to deterministic logic for supported workflows when it is unavailable.

## 2. Collection Layer

All sources are normalized into the same `live_jobs` model before matching.

```text
Arbeitnow ──────────────────────────┐
Jobicy ─────────────────────────────┤
Lever employer postings ────────────┤
SmartRecruiters postings ───────────┤
Ashby public Job Postings API ──────┤
Authorized external collector ──────┤
Manual / bulk import ────────────────┤
                                    ↓
                              normalization
                                    ↓
                              deduplication
                                    ↓
                              PostgreSQL
```

Configured employer ATS collectors are managed from **Settings**.

Current direct ATS providers:

- Lever global
- Lever EU
- SmartRecruiters
- Ashby

XING and StepStone remain authorized/manual-import sources rather than default automated collectors.

## 3. Match Layer

The Match Layer lives in `backend/app/match_layer.py`.

```text
uploaded CV
    +
normalized job
    ↓
requirement extraction
    ├── required skills
    ├── preferred skills
    ├── role family
    ├── explicit experience requirement
    ├── explicit language requirement
    └── location / remote signal
    ↓
explainable score
```

Current score weights:

```text
Role alignment          30%
Required skills         30%
Preferred skills        10%
Experience              15%
Language                10%
Location                 5%
```

The report includes matched/missing required skills, preferred skills, hard blockers, reasons and an `eligible_for_preparation` decision.

The score is decision support. It is not an interview probability.

API:

```http
GET /api/jobs/{job_id}/match-report
```

## 4. Application Preparation Layer

The preparation layer lives in `backend/app/application_preparation.py` and persists snapshots in the `application_packages` table.

```text
selected job
    +
latest CV
    +
Match Layer report
    ↓
cover letter
    +
safe screening-answer drafts
    +
validation checks
    ↓
ApplicationPackage
    ↓
Application Prep page
```

Prepared automatically:

- exact job/company/source/application URL snapshot
- CV profile reference
- structured match report
- CV-grounded cover letter
- draft answers for role motivation and relevant experience
- validation against the chosen minimum match

Deliberately requires user input when the app cannot safely know the answer:

- work authorization / visa
- salary expectation
- start date / notice period
- language level when not evidenced in the CV

Package states:

```text
Needs Review
→ user completes unresolved fields
→ Package Ready
```

"Package Ready" means preparation is complete. It does not mean submission occurred.

APIs:

```http
POST  /api/jobs/{job_id}/prepare-application
GET   /api/application-packages
GET   /api/application-packages/{package_id}
PATCH /api/application-packages/{package_id}/answers
POST  /api/application-packages/{package_id}/cover-letter
```

## 5. Application CRM

The CRM remains the source of truth for actual outcomes:

```text
Saved
→ Applied
→ Screening
→ Interview
→ Final
→ Offer / Rejected
```

A package is separate from an actual submitted application.

## 6. Future Submission Layer

The next stage remains approval-first:

```text
Package Ready
      ↓
human review + approve
      ↓
provider adapter
  ├── authorized ATS application API
  └── permitted employer-site browser adapter
      ↓
confirmed submission result
      ↓
Application CRM → Applied
```

The system should never treat a heuristic match threshold alone as permission to submit an application.

## 7. Advanced data path

Optional data-engineering services remain available:

```text
collectors
   ↓
Redpanda/Kafka
   ↓
normalization/events
   ↓
PostgreSQL
   ↓
Airflow + dbt
   ↓
ClickHouse
   ↓
market/application analytics
```

Start them with:

```bash
docker compose --profile data up --build
```

## 8. Product principles

- No paid API keys required for the core local workflow.
- Prefer public/authorized source interfaces over brittle scraping.
- Keep collection, matching, preparation and submission as separate layers.
- Keep CV/application data local by default.
- Expose score reasons rather than only a percentage.
- Never invent personal screening answers.
- Preserve human approval before actual submission until provider-specific automation is proven reliable.

See also:

- `docs/DATA_SOURCES.md`
- `docs/MATCH_AND_PREPARATION.md`
- `docs/APPLICATION_AUTOMATION_ARCHITECTURE.md`
