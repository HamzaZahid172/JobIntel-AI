# P1 — Interview practice, conversion analytics and employer ATS sources

## Interview Practice
From **Action Center / Job Market** click **Interview Prep** on a vacancy, or open the new **Interview Practice** sidebar page to resume saved sessions. JobIntel generates six representative QA Automation, Data Engineering or Backend/Software interview questions based on the role, and highlights verified overlapping skills from the saved CV. Submit real example answers for coaching on personal contribution, technical relevance, structure and results; answers are saved privately in `interview_practices`.

This coach does **not** infer actual interview questions or guarantee offers. Do not paste passwords or confidential employer information into practice answers.

## Conversion analytics
Analytics now exposes role-family and CV-version application metrics. Counts come from your own saved applications and statuses, not inbox scraping or fabricated predictions. The initial sample is likely too small for conclusions; fewer than 30 applications explicitly produce a small-sample warning.

## Employer ATS
Settings now supports company-board identifiers for two more official public sources:
- **Personio** — `<company>.jobs.personio.de/xml?language=en` (requires employer-enabled XML feed).
- **Workable** — `https://www.workable.com/api/accounts/<company>?details=true` (official public jobs endpoint).

Only store genuine public postings for Germany or remote-EU technical roles. These integrations collect listings only; they do not submit candidate information or bypass employer login/CAPTCHA. Invalid company identifiers and foreign-location postings are rejected. Providers that disable their public feeds may legitimately return zero jobs.

## Upgrade and quality checks
New model table `interview_practices` is created by existing SQLAlchemy model initialization. Existing data remains in PostgreSQL. Before upgrading, back up database:
```bash
docker compose exec -T db pg_dump -U jobintel jobintel > jobintel-before-p1.sql
docker compose up -d --build
```
Unit tests verify employer feeds from representative mocked public payloads, interview questions and feedback, and analytics with small sample limits. They cannot guarantee that every external employer API or live role is currently available.
