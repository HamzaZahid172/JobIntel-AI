# Interview funnel recovery: quality before application volume

This release repairs specific inconsistencies that can distort JobIntel-AI recommendations and application analytics. It does not claim to control employer decisions.

## Problems corrected
1. CV consistency: job lists, standalone match reports, cover letters and application preparation use the saved default role-specific CV (QA / backend / data) where available.
2. Source integrity: missing vacancy location is not replaced with Germany. Jobicy location rows must explicitly allow Germany or a broader Europe/worldwide region.
3. Posting age integrity: a manually imported job without the employer's posting date keeps an unknown posting date. Ingestion time is not posting time.
4. Job priority: public aggregator scores stay Review until the employer careers page is independently confirmed. Employer ATS feed source also does not guarantee the vacancy is open.
5. Application tracking: opening the manual tracker defaults to Saved, not Applied; choosing Applied requires explicit confirmation.
6. Funnel diagnostics: analytics show missing CV versions, source URLs, documented submission confirmations and pending applications older than 14 days. Missing documentation does not prove a failed submission.

## Improve candidate material
Create separate single-column CVs tailored to QA Automation / SDET, Backend Python, and Data Extraction / Data Engineering. Use verified experience only. Do not commit personal CV PDFs or identity documents to a public GitHub repo.

Check Arbisoft official job titles against the experience letter (Data Analyst, Junior Software Engineer, Software Engineer, Senior Software Engineer). Do not claim unrestricted full-time authorization without checking residence permit conditions.

## ChatGPT Plus workflow without API integration
1. In ChatGPT, review each employer job description together with your relevant CV and draft screening responses.
2. Ask for an evidence matrix: supported, missing, or needs confirmation. Do not fabricate jobs, degrees, certifications or skills.
3. Edit the CV privately and upload the revised PDF under the correct JobIntel CV family.
4. Verify the original employer vacancy, language requirements and work eligibility.
5. Save employer submission confirmation and the real CV filename, then compare observed outcomes by role track.

ChatGPT Plus does not automatically give a custom FastAPI project free API access; API billing is separate. Keep local deterministic/Ollama options until a separately priced API integration is explicitly approved.

## Actual success metrics
Verified direct employer jobs, role-specific applications, confirmed submissions, recruiter replies, first-stage interviews, and interview rates by CV track. Heuristic match percentages are not hiring probabilities.

## Scope limitation
GitHub CI covers unit tests and frontend syntax/Compose checks. Live employer form submissions, local Docker build and real interview outcomes require separate manual validation. No application was submitted by this release.
