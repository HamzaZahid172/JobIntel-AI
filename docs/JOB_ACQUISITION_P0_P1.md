# JobIntel AI: P0 and P1 Job Acquisition

## P0: Gmail message reliability

The existing Gmail connection is kept read-only. The sync now uses the Gmail Messages List endpoint with `includeSpamTrash=true`, query `in:anywhere -in:spam newer_than:45d`, and pagination. The default sync scans at most 300 recent messages, and returns `listed`, `scanned`, `matched`, and `updated` counts.

A Gmail outcome updates an application only when the email is classified and the tracked employer can be identified. If multiple applications at the same employer are ambiguous, JobIntel deliberately does not guess. Emails older than the application's application date are ignored. The system still cannot recover messages permanently deleted from Gmail. Sync after your regular application activity so older messages are processed before the 45-day horizon.

## P1: New ranking and sources

`/api/jobs` includes an `opportunity` object with a heuristic priority score, decision, age, track and reasons. This is **not** an employer response probability.

Remotive is added to Arbeitnow/Jobicy. It is a remote feed and only jobs open to Germany, Europe/EMEA or worldwide candidates are kept; US-only roles are excluded. Remotive listings preserve the original URL and attribution. Remotive API requests are throttled to at least six hours apart, even if users repeatedly click refresh. Source failures retain the previously stored snapshot of that source.

Employer ATS collectors remain: Greenhouse, Lever, Ashby and SmartRecruiters. University portals such as JobTeaser still require user access, alerts, or explicit permitted import; no undocumented scraping was introduced.

## P1: Endpoints and dashboard

- `GET /api/action-center`: up to 12 untracked, ranked opportunities and due follow-ups, scoped to current user
- `GET /api/cv/versions`: list current user's previously uploaded CVs
- `GET /api/jobs/{job_id}/tailor-cv?cv_id=...`: suggested summary and verbatim CV evidence for user review
- `POST /api/jobs/{job_id}/prepare-application` with optional `cv_id`: prepare from a selected CV owned by current user
- `POST /api/applications/{id}/follow-up-sent`: only after user confirms the message was sent; records a timestamp in notes

Action Center allows manual opening of employer links, preparation of application packages, CV version selection and **draft-only** recruiter follow-up emails. Nothing is auto-sent, deleted, or submitted.

## Basic acceptance test

1. Pull latest `main`, rebuild Docker and upload a CV.
2. Refresh jobs; check the Remotive source and opportunity badges.
3. Open Action Center and prepare one job using a selected CV.
4. Connect Gmail, run Sync now, and check the listed/scanned/matched/updated breakdown.
5. Put a *recent* known rejection in Gmail Trash (not permanently deleted); check that matched status becomes Rejected and appears under Show rejected.
6. Check a 7+ day old Applied application for follow-up. Copy the draft, send it manually, then click I sent this follow-up. It should disappear from the due queue temporarily.
7. If two jobs at the same employer are being tracked and the email does not identify which role, status should **not** be changed automatically.

`python -m pytest backend/tests -q` and `node --check frontend/app.js` are covered by repository CI, but the user must still test the live OAuth flow locally.
