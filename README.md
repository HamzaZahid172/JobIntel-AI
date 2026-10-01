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
- UI: http://localhost:3000
- API docs: http://localhost:8000/docs
- API health: http://localhost:8000/health

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
curl http://localhost:8000/health
```

Expected output:

```json
{"status":"ok"}
```

The backend now retries database connectivity during startup, so a transient Docker Desktop DNS delay will not immediately terminate the API.
