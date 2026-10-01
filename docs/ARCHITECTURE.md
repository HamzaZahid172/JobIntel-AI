# Architecture

## Core runtime

Browser → React/Vite/Nginx → FastAPI → PostgreSQL

FastAPI owns manual applications, dashboard aggregates, ATS parsing, CV/job matching, suggestions and the local AI-assistant tool layer. Ollama is optional and local; deterministic fallbacks keep the product usable without an LLM.

## Advanced data path

Free/public job source → collector → Redpanda/Kafka → normalizer → PostgreSQL → Airflow/dbt → ClickHouse → analytics API → WebSocket-ready dashboard.

The advanced data services are started with `docker compose --profile data up --build` so the default laptop setup stays lightweight.

## Product principles

- No paid API keys required.
- Manual applications first; automation later.
- ATS Readiness, not fake “ATS approval”.
- Interview readiness is not presented as a true probability until enough labelled historical outcomes exist.
- Personal CV/application data stays local by default.
