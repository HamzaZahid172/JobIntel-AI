# JobIntel AI roadmap

## Core product

1. Foundation + dashboard UI ✅
2. CV profile + ATS intelligence ✅
3. Manual application CRM ✅
4. Job-to-CV matching engine ✅
5. Explainable Match Layer ✅ v0.7
6. AI improvement engine ✅
7. Local AI Career Assistant ✅ Ollama + fallback
8. Free/public job discovery ✅ Arbeitnow + Jobicy
9. Direct employer ATS collectors ✅ Lever + SmartRecruiters + Ashby
10. CV-first market intelligence dashboard ✅
11. Cover-letter generation ✅ DOCX
12. Authentication + local user profile ✅
13. External collector bridge ✅ normalized bulk import
14. Application Preparation Layer ✅ v0.7
15. Application Prep review UI ✅ v0.7
16. Kafka event architecture ◐ Redpanda profile + event contract
17. Airflow + dbt analytics ◐ starter DAG/model
18. ML interview readiness ◐ requires labelled outcomes
19. Observability + deployment hardening ◐ Prometheus/OTel/Kubernetes/IaC
20. Portfolio release ✅ one-command local Docker runtime

## Next: Intelligent Application Engine submission stage

21. Ready-to-Apply queue rules ◐ preparation packages exist; automatic queue policy next
22. Screening-question extraction from provider-specific application forms ☐
23. Human approval workflow ☐
24. Authorized ATS submission adapters ☐
25. Employer-site browser fallback where permitted ☐
26. Submission audit + duplicate prevention ☐
27. Optional rules-based auto-submit after reliability validation ☐

See:

- `docs/MATCH_AND_PREPARATION.md`
- `docs/APPLICATION_AUTOMATION_ARCHITECTURE.md`

Legend: ✅ usable now, ◐ partially implemented/scaffolded, ☐ planned.
