# JobIntel AI Architecture

## 1. Product runtime

The default local runtime is intentionally free and laptop-friendly:

```text
Browser
   ↓
Nginx static frontend (HTML/CSS/JavaScript)
   ↓
FastAPI API
   ├── authentication/profile
   ├── CV parsing + ATS Readiness
   ├── CV-first job matching
   ├── application CRM
   ├── cover-letter generation
   ├── Career Assistant
   └── source/collector orchestration
   ↓
PostgreSQL
```

Ollama runs as a local Docker service. JobIntel uses it when the configured model is ready and falls back to deterministic logic for supported workflows when the model is unavailable.

## 2. Job acquisition layer

All sources are normalized into one `live_jobs` schema before matching.

```text
Arbeitnow public API ───────────────┐
Jobicy public API ──────────────────┤
Lever public employer postings ─────┤
SmartRecruiters public postings ────┤
Ashby public Job Postings API ──────┤
Authorized external collector ──────┤
Manual job import ──────────────────┤
                                    ↓
                              normalization
                                    ↓
                              deduplication
                                    ↓
                              PostgreSQL
```

Configured employer ATS collectors are user-controlled in **Settings**. A target consists of a provider, a company/job-board identifier, a display label and an enabled state.

Current direct ATS providers:

- Lever global
- Lever EU
- SmartRecruiters
- Ashby

For Ashby, the identifier is the final path component of the company's hosted job board, for example `CompanyName` from `https://jobs.ashbyhq.com/CompanyName`.

XING and StepStone are not default automated collectors. Jobs from restricted platforms should enter through an authorized integration or the manual/bulk-import bridge.

## 3. Career intelligence layer

```text
uploaded CV
   ↓
text extraction
   ↓
ATS Readiness + CV skill profile + role families
   ↓
normalized current jobs
   ↓
role relevance + skill overlap + experience/language signals
   ↓
CV-relevant jobs
   ↓
matches / skill gaps / recommendations / analytics
```

ATS Readiness is a structural/readability heuristic, not a universal ATS certification.

## 4. Application preparation

For a selected job:

```text
CV + exact stored job description
        ↓
matched/missing skills
        ↓
local Ollama when available
        or grounded deterministic fallback
        ↓
tailored cover letter
        ↓
DOCX download
```

Application status remains user-owned in the CRM.

## 5. Intelligent Application Engine architecture

The next application-automation stage is deliberately approval-first:

```text
Job acquisition
      ↓
CV match + hard filters
      ↓
Ready-to-Apply queue
      ↓
prepare package
  ├── selected CV
  ├── cover letter
  ├── screening answers
  └── source/application URL
      ↓
human review + approve
      ↓
provider adapter
  ├── official ATS application API where authorized
  └── employer-site browser adapter where permitted
      ↓
submission receipt/result
      ↓
application CRM → Applied
```

### Hard filters before a job can enter Ready-to-Apply

A high match score alone is not enough. The future queue should also validate:

- target role family
- Germany / accepted remote-EU location
- language requirements
- employment type
- work authorization / relocation constraints when known
- user-defined salary constraints when known
- required screening answers
- duplicate-application prevention

### Automation states

```text
Discovered
→ Matched
→ Ready to Prepare
→ Package Ready
→ Awaiting Approval
→ Submitting
→ Applied
→ Screening
→ Interview
→ Final
→ Offer / Rejected
```

No production workflow should silently treat a heuristic 90% score as permission to submit an application. The first automation version should prepare everything automatically but require a final user approval before submission.

## 6. Advanced data path

The optional data profile remains available for experimentation:

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

Start optional data services with:

```bash
docker compose --profile data up --build
```

## 7. Product principles

- No paid API keys required for the core local workflow.
- Prefer public/authorized source interfaces over brittle scraping.
- Keep acquisition adapters separate from matching/business logic.
- Keep CV/application data local by default.
- Explain match reasons instead of only showing a score.
- Preserve human approval for application submission until provider-specific automation is proven reliable.
- Never present interview-readiness heuristics as a real probability without sufficient labelled outcomes.
