# JobIntel AI P0 — Document Vault, Candidate Profile, Cover Letters and Assisted Apply

## Upgrade without losing existing applications
The release adds **two new tables** (`candidate_documents`, `candidate_profiles`); existing CV profiles, applications, Gmail events and tracked statuses are not removed. Existing tables continue to be created with SQLAlchemy `metadata.create_all`. Back up the PostgreSQL and new document volume together before upgrading:

```sh
docker compose exec -T db pg_dump -U jobintel jobintel > jobintel-backup.sql
docker compose up -d --build
```

Back up the Docker `documents_data` volume with the same retention as PostgreSQL. It holds encrypted files **and the Fernet key**; losing the key permanently prevents document recovery. The container initializes a random persisted key if `JOBINTEL_DOCUMENT_KEY` is unset. Never commit secrets or the volume contents to GitHub. Encryption at rest is not a substitute for Mac disk security or secure backup access.

## One-time setup

1. Open **Settings → Private document vault**. Existing extracted CV text alone cannot be reconstituted into an original PDF. Upload your original CV once again to populate the vault. Select the matching CV role family (General, QA, Data Engineering, Backend/AI). The CV upload route still performs ATS analysis and preserves that CV's extracted text, and now also saves the original bytes.
2. Upload your **experience letter** once. Keep it marked as the default general supporting document.
3. Complete **Settings → Saved application profile**, confirm each field, and save. The email address comes from your authenticated JobIntel account, not parsed guesses.
4. Open an opportunity → **Assisted Apply**. The verified profile is prefilled. The stored CV is chosen by role; a local file override always takes precedence. JobIntel prepares a job-specific cover letter using the original CV profile associated with the chosen document and the selected job. Read or edit the draft and choose whether to include it.
5. Click **Open Employer in Chromium**, inspect the real employer form, fill only approved known fields and recognized attachments, review the answers, then type **SUBMIT** to approve the final employer action. Login, CAPTCHA, salary, work authorization, demographics and consent require your own input. Clicking Submit is never mistaken for verified success; confirm the actual employer acknowledgment before tracking Applied.

The browser companion remains a separate local process:
```sh
cd browser-assistant
npm install
npx playwright install chromium
npm start
```

The assistant will never submit jobs in bulk or send job applications without explicit user approval. Some ATS platforms or custom forms may require manual actions, especially iframes, selectors and asynchronous uploads.

## Endpoints

- `GET/PATCH /api/candidate-profile`: user-approved form details; extra fields rejected.
- `GET /api/documents`: private owner-scoped document metadata.
- `POST /api/documents?kind=experience`: save an optional experience letter (PDF/DOCX/DOC/TXT, <=8 MB).
- `POST /api/cv/upload?role_family=data`: analyze and store the original CV.
- `GET /api/documents/selected?job_id=...`: role-based CV selection and optional supporting files.
- `GET /api/documents/{id}/content`: authenticated decryption and base64, used only when applying.
- `POST /api/documents/{id}/default`: update the CV/letter default version within a role.
- `POST /api/jobs/{id}/prepare-application`: candidate/job-specific cover letter in the prepared application package.
- `POST /api/jobs/{id}/cover-letter-render`: convert approved, editable draft to an attachable DOCX.

No external paid API is necessary; JobIntel attempts its local Ollama model first and uses a CV-grounded fallback if unavailable or if the generated draft fails the basic factual guard. AI-drafted letters must still be reviewed for accuracy.

## Security and limitations

- Documents are authenticated and user-scoped. Original files are kept encrypted in `/data/documents` (persistent Docker volume) and never included in logs.
- Treat the Mac running `127.0.0.1:3401` and `localhost:3100` as trusted. The local browser assistant processes plaintext bytes in memory during a chosen application session, discarding them when closed.
- Uploaded documents have extension, size, and basic signature checks, not a complete malware scan.
- Candidate information must be verified by the user. Automatically parsing or guessing a visa status or salary declaration is disallowed.
- Backend unit tests, browser helper tests, syntax checks and `docker compose config --quiet` run in CI; employer production websites need supervised manual validation.
