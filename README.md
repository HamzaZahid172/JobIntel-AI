# JobIntel AI

Local-first, zero-paid-service career intelligence platform for Germany-focused tech job search.

## What works now

- High-fidelity responsive dashboard inspired by the approved UI mockup (zero-dependency static frontend for reliable local Docker builds)
- Manual application tracking and pipeline
- Persistent Application Preparation packages with safe screening drafts
- ATS Readiness score and CV parsing endpoint
- Explainable Match Layer: role, required/preferred skills, experience, language and location
- Improvement suggestions (Kafka, Airflow, Terraform, German, CV targeting)
- Job matches, skills-in-demand view, performance cards and follow-ups
- Embedded Career Assistant with local Ollama and deterministic fallback
- PostgreSQL persistence
- Docker Compose one-command startup
- Backend tests and GitHub Actions CI
- Optional free data-engineering profile with Redpanda + ClickHouse
- Airflow/dbt/ML/Kubernetes/Terraform scaffolds for later data-dependent stages


## Job Acquisition P0/P1 (October 2026)

- **Gmail reliability (P0)**: syncs multiple Gmail result pages (up to 300 recent messages); explicitly includes Trash and excludes Spam; checks company and role evidence; refuses ambiguous multi-role matches; protects applications against emails dated before the application. Permanently deleted Gmail messages cannot be recovered.
- **Opportunity Score (P1)**: a separate explainable priority heuristic combining CV match, freshness, direct-employer sources and role alignment. Shows Apply Now / Review / Skip decisions; hard blockers force Skip.
- **More job sources (P1)**: Remotive added to Arbeitnow and Jobicy, alongside configurable Greenhouse, Ashby, Lever and SmartRecruiters employer boards. Remotive listings link to and acknowledge Remotive; we do not republish to other boards. Limited Remotive polling (6h minimum) respects its public API guidance.
- **Action Center (P1)**: best opportunities and recruiter follow-ups in one queue; already-tracked vacancies omitted from suggestions.
- **CV tailoring (P1)**: preview evidence-based text grounded in an uploaded CV; select from your uploaded CV versions before preparation. Never fabricates skills, and never silently changes or sends your CV.
- **Follow-up assistant (P1)**: after seven days, drafts a company/role-specific email for manual review and sending. A separate explicit "I sent this" action records the follow-up and suppresses immediate duplicates.

### Safety and control

JobIntel **does not auto-submit job applications or send Gmail messages**. It uses Gmail read-only scope, and cannot send emails with that scope. Review every application, CV suggestion and outreach draft before using it. For Gmail/Remotive integration specifics and API endpoints, see `docs/JOB_ACQUISITION_P0_P1.md`.

## Run

```bash
cp .env.example .env
docker compose up --build
```

Open:
- UI: http://localhost:3100
- API docs: http://localhost:8100/docs
- API health: http://localhost:8100/health

### Local LLM

The default Docker Compose stack starts Ollama locally and an init container ensures the configured model is available:

```env
OLLAMA_MODEL=llama3.2:3b
USE_OLLAMA=true
```

No paid AI API is required. If Ollama is still starting/downloading or is disabled, supported assistant and cover-letter flows fall back to deterministic local logic.

### Optional data-engineering services

```bash
docker compose --profile data up --build
```

This additionally starts Redpanda (Kafka-compatible) and ClickHouse.

## Important scoring language

JobIntel reports **ATS Readiness**, not “ATS Approved”. No universal ATS certifies a CV. The score checks parsing, sections, contact readability, keywords and content structure.

The current **Interview Readiness** score is a decision-support heuristic. A true outcome probability will only be trained after enough labelled application outcomes exist.

## Architecture and roadmap

See `docs/ARCHITECTURE.md` and `docs/ROADMAP.md`.


## Troubleshooting Docker Desktop

If you previously started an older version of the stack and the backend shows a PostgreSQL error such as:

```text
Temporary failure in name resolution
```

pull the latest code and recreate the Compose network/containers:

```bash
git pull origin main
docker compose down --remove-orphans
docker compose up --build --force-recreate
```

For the optional Redpanda + ClickHouse profile:

```bash
docker compose --profile data down --remove-orphans
docker compose --profile data up --build --force-recreate
```

Check that the API is healthy:

```bash
curl http://localhost:8100/health
```

Expected output:

```json
{"status":"ok"}
```

The backend now retries database connectivity during startup, so a transient Docker Desktop DNS delay will not immediately terminate the API.


## Running JobIntel alongside other Docker projects

JobIntel intentionally uses its own host ports so projects such as GreenOps AI can stay running at the same time:

- JobIntel UI: `http://localhost:3100`
- JobIntel API: `http://localhost:8100`
- JobIntel PostgreSQL host port: `5433`
- Optional Redpanda host port: `19092`
- Optional ClickHouse HTTP/native ports: `18123` / `19000`

Inside Docker, the backend still connects to PostgreSQL using the Compose service address `db:5432`. Host ports do not affect service-to-service communication.

If Docker Desktop previously created stale JobIntel containers or networks, use this clean restart:

```bash
git pull origin main
docker compose --profile data down --remove-orphans
docker compose down --remove-orphans
docker compose up --build --force-recreate
```

If Docker Desktop itself reports an HTTP 500 container-networking error, quit and reopen Docker Desktop once, then run the commands above again. That error comes from Docker Desktop's network engine rather than the FastAPI application.


## Live data and CV workflow

JobIntel no longer uses demo market numbers. The dashboard is calculated from records stored in PostgreSQL.

### Current job feeds

The core build uses free public job feeds that do not require paid API keys:

- **Arbeitnow** for current Europe/Germany-focused jobs.
- **Jobicy** for current remote jobs filtered to Germany.

JobIntel filters the feeds toward software engineering, backend, data engineering, QA automation, AI/ML, platform/DevOps and working-student roles, normalizes the listings, extracts technical skills, stores the current snapshot in PostgreSQL, and preserves the source job URL.

Use the dashboard button **Refresh Current Jobs**, or call:

```bash
curl -X POST http://localhost:8100/api/jobs/sync
```

### Upload your CV

From the **ATS CV Check** card, upload a PDF, DOCX or TXT CV. JobIntel will:

1. extract the CV text locally,
2. calculate ATS Readiness,
3. detect technical skills,
4. store the CV profile in your local PostgreSQL database,
5. rescore every currently stored job against that CV,
6. rebuild skill-gap and interview-readiness cards from the live job snapshot.

Your CV is not sent to Arbeitnow or Jobicy.

### After updating from the earlier demo build

Pull and rebuild:

```bash
git pull origin main
docker compose down --remove-orphans
docker compose up --build --force-recreate
```

Open:

- Dashboard: http://localhost:3100
- API: http://localhost:8100
- API docs: http://localhost:8100/docs

The first backend startup may take a little longer because it performs an initial live-job sync when the local live-jobs table is empty.


## CV-first job filtering

After a CV is uploaded, JobIntel no longer ranks the dashboard from the whole market indiscriminately.

It builds a profile from the CV, including:

- strongest programming languages and tools,
- repeated skill evidence,
- target role families such as Software/Backend, QA Automation, Data Engineering, Frontend/Full-stack and DevOps/Platform,
- ATS readiness.

The dashboard then filters current jobs using both **role relevance** and **skill overlap**. Generic sales, account-management, product-management and finance/analyst roles are prevented from receiving high match scores merely because their descriptions mention APIs or data.

The **Your Top Skills + Current Demand** card is CV-first. It shows how strongly a skill appears in the uploaded CV and how often that same skill appears in the current CV-relevant job set.

The ATS score is generic readiness and is capped below 100 by design. Job-specific compatibility is reported separately in the Best Current Matches section.


## v0.4 app navigation and login

JobIntel now requires a local account before opening the career workspace. Registration creates a profile and claims any CV/application data from older pre-login local versions.

The sidebar pages are functional:

- **Dashboard** – CV-filtered market overview and Career Assistant.
- **Job Market** – all CV-relevant jobs, search/filter controls, source links, application tracking and manual job import.
- **My Applications** – application table with editable pipeline status.
- **ATS CV Check** – upload/replace the CV and review ATS readiness + strongest skills.
- **Matches** – current jobs ranked against the CV.
- **Skill Gap** – repeated missing skills across CV-relevant jobs.
- **Analytics** – application funnel, source counts and CV-version outcomes.
- **Settings** – profile, target roles/locations, Ollama status and source strategy.

The Career Assistant reports whether it is using local **Ollama** or the deterministic fallback rules. Configure Ollama in `.env` with `USE_OLLAMA=true`.

See `docs/DATA_SOURCES.md` for the XING/StepStone strategy. JobIntel does not automatically scrape those platforms without authorized access; individual jobs can be imported from the Job Market page.


## v0.5 collectors + cover letters

JobIntel can now add employer-specific **Lever**, **SmartRecruiters**, and **Ashby** posting collectors from Settings. These use official/public posting interfaces and feed the same PostgreSQL job pipeline.

Existing external collectors can integrate through `POST /api/jobs/bulk-import`, so a Playwright collector can remain an isolated data-collection process instead of becoming part of the dashboard runtime.

Every matched job now has **Create cover letter**. The backend uses the current CV plus the stored job description and downloads a tailored `.docx`. Ollama is used when enabled and reachable; otherwise a grounded deterministic template is generated.

See `docs/COLLECTORS_AND_COVER_LETTERS.md`.


## v0.6 Ashby + application automation architecture

Ashby is now a configurable direct employer source. In **Settings → Direct employer ATS collectors**, add:

- Provider: `Ashby`
- Company label: the employer name
- Identifier: the final path component of the employer's Ashby board, for example `CompanyName` from `https://jobs.ashbyhq.com/CompanyName`

**Refresh Current Jobs** combines Arbeitnow, Jobicy and all configured Lever / SmartRecruiters / Ashby targets before CV filtering and matching.

The next product stage is documented as the **Intelligent Application Engine**:

```text
Ready-to-Apply queue
→ application package
→ screening answers
→ human approval
→ authorized provider submission
→ application CRM
```

See `docs/APPLICATION_AUTOMATION_ARCHITECTURE.md`.

The existing external collector bridge remains available at `POST /api/jobs/bulk-import`.


## v0.7 Match + Application Preparation layers

The CV-to-job flow is now split into explicit production layers.

### Match Layer

Each job receives an explainable score with these dimensions:

```text
Role alignment          30%
Required skills         30%
Preferred skills        10%
Experience              15%
Language                10%
Location                 5%
```

The report exposes required/preferred skills, matched/missing skills, hard blockers and preparation eligibility.

API:

```text
GET /api/jobs/{job_id}/match-report
```

### Application Preparation Layer

Job Market and Matches now include **Prepare application**. Preparation creates a persistent package containing:

- current CV reference
- exact job snapshot
- structured match report
- generated cover letter
- safe screening-answer drafts
- validation checks
- unresolved fields that need real user input

The sidebar now includes **Application Prep**, where those packages can be reviewed, screening answers can be completed and the package-specific cover letter can be downloaded.

JobIntel deliberately does not invent work-authorization, salary, notice-period or unsupported language-proficiency answers.

APIs:

```text
POST  /api/jobs/{job_id}/prepare-application
GET   /api/application-packages
PATCH /api/application-packages/{package_id}/answers
POST  /api/application-packages/{package_id}/cover-letter
```

See `docs/MATCH_AND_PREPARATION.md` and `docs/ARCHITECTURE.md`.


## v0.7.1 Analytics + source visibility fix

Analytics now distinguishes **supported/configurable sources** from sources that currently have stored jobs. Arbeitnow, Jobicy, Ashby, Lever and SmartRecruiters are always visible in source analytics, including zero-job and not-configured states.

Skill Gap now uses the structured Match Layer's **missing required** and **missing preferred** skills instead of a flat extracted-keyword comparison.

See `docs/V0.7.1_ANALYTICS_FIX_REPORT.md`.
