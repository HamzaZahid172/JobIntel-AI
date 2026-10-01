# JobIntel AI

Local-first, zero-paid-service career intelligence platform for Germany-focused tech job search.

## What works now

- High-fidelity responsive dashboard inspired by the approved UI mockup (zero-dependency static frontend for reliable local Docker builds)
- Manual application tracking and pipeline
- ATS Readiness score and CV parsing endpoint
- CV-to-job skill matching and explainable gaps
- Improvement suggestions (Kafka, Airflow, Terraform, German, CV targeting)
- Job matches, skills-in-demand view, performance cards and follow-ups
- Embedded Career Assistant with deterministic answers and optional local Ollama
- PostgreSQL persistence
- Docker Compose one-command startup
- Backend tests and GitHub Actions CI
- Optional free data-engineering profile with Redpanda + ClickHouse
- Airflow/dbt/ML/Kubernetes/Terraform scaffolds for later data-dependent stages

## Run

```bash
cp .env.example .env
docker compose up --build
```

Open:
- UI: http://localhost:3100
- API docs: http://localhost:8100/docs
- API health: http://localhost:8100/health

### Optional local LLM

Install Ollama locally, pull a free model, then set:

```env
USE_OLLAMA=true
OLLAMA_MODEL=llama3.2:3b
```

No paid AI API is required. Without Ollama, the Career Assistant uses deterministic local guidance.

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
