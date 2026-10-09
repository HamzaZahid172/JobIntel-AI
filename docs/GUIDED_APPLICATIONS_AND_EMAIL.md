# JobIntel Guided Job Applications (v1.1)

## Goals and boundaries

The system assists with real employer applications **on the applicant's own Mac**. It is not a bot that creates hundreds of unattended applications. It does not bypass CAPTCHA, paywalls, verification challenges, or account protections. It never fabricates work authorization, salary requirements, qualifications, demographic answers, or consent.

## One-time setup (Node.js 20 or newer)

From the project root, run `docker compose up -d --build`. In a second Mac terminal:

```bash
cd browser-assistant
npm install
npx playwright install chromium
npm start
```

Keep the second terminal running. It binds to `127.0.0.1:3401`, so it cannot be reached from other computers on your network. It runs headed Chromium (visible). Mac permissions may ask before allowing the browser to open.

## Browser-assisted Apply workflow

1. Open JobIntel at http://localhost:3100 → Action Center or Job Market → **Assisted Apply** next to the right vacancy. Check this is the employer's real job posting and not an unrelated third-party listing.
2. Verify name, email, and optional contact/profile links. Select CV (required), cover letter and experience/reference letter (optional). Supported: PDF/DOC/DOCX/TXT, up to 8 MB each.
3. Click **Open Employer in Chromium**. A new browser appears on the desktop.
4. On a listing page, use **Next / Continue** to move to the form where possible, or click the employer's Apply button yourself. Review the site before trusting it with documents.
5. Click **Fill Known Fields & Attach**. Recognized names, email, phone, city, LinkedIn, GitHub, portfolio and named attachments are filled if the destination fields are empty. Unknown questions must be completed by you in the visible browser.
6. Click **Inspect Form** to see required/unfilled fields. Continue/repeat as needed. Read GDPR consents, eligibility questions and any employer-specific conditions.
7. Review every answer, attachment, destination URL and confirmation. Type **SUBMIT**, confirm the modal, and click **Approve Final Submission**. The worker will click only a uniquely identifiable final Submit button. If ambiguous, it refuses and asks you to finish manually.
8. **Verify the employer confirmation page or email yourself**. Only then click **I verified employer confirmation — Track application** in JobIntel. Do not retry blindly if the employer site is processing the first submission.
9. Close the browser session and stop the companion process when finished.

This assistant supports standard HTML inputs, not every embedded iframe, popup, React widget, OAuth sign-in, file chooser, CAPTCHA or special-purpose portal. No guarantee is made of universal automatic submission. Attachments are held in volatile worker memory during the session rather than a hosted service; sensitive files are only passed to the employer when you choose the employer form and upload.

## Local ATS simulation

**ATS Review** provides a job-specific readiness check against an uploaded CV, including:
- Generic ATS readiness based on the CV text
- Readability/contact/experience/education/skills section checks
- Required-skill evidence coverage, missing evidence and language/role blockers
- Specific suggestions without claiming skills absent from the CV

An employer's ATS may evaluate applications differently. No free universal ATS exposes an objective approval probability. For actual job qualification rely on the employer description and truthful application materials.

## Gmail sending (optional)

Your existing Gmail OAuth scope is read-only. To enable sending follow-ups:

1. In Google Cloud Console for your JobIntel OAuth project, go to **Google Auth Platform → Data Access**. Add `https://www.googleapis.com/auth/gmail.send`, leaving `https://www.googleapis.com/auth/gmail.readonly` selected.
2. Confirm your Gmail is an authorized test user in **Audience** if the app is in Testing. The scope may trigger additional Google consent/verification requirements.
3. In JobIntel **Settings → Enable Gmail sending**, authorize the new permission in Google's sign-in tab, and refresh Settings. It should show **Send authorized**.
4. Open Action Center → Follow-ups, enter a verified hiring-team address and edit the subject/body; click **Review & Send via Gmail** and approve the confirmation.
5. Gmail's successful API response records the follow-up in JobIntel. You can verify delivery in Gmail Sent. If send permission is not granted, use **Copy draft** and manual email instead.

**Never send to a no-reply address.** Application follow-ups are suggested only for due, open applications. The system does not guess recruiter addresses or send repeated unsolicited emails. It uses Gmail's official Send API with the user's consent, not a hidden SMTP password. Gmail connection tokens are stored in the local Postgres database under the application's existing connection implementation; protect your machine and database and do not publish your .env credentials.

## Job sources

JobIntel already connects free public feeds Arbeitnow, Jobicy and Remotive, plus manually configured public employer ATS boards Greenhouse, Lever, Ashby, SmartRecruiters. Some companies use these ATS platforms; public job discovery does **not** mean the applicant possesses employer-only API credentials for submissions. Applications therefore use the visible public employer forms, not protected server-side POST keys.

## Validation

GitHub CI checks backend tests, frontend JS syntax, worker JS syntax and the local worker's pure helper tests. This verifies source quality but cannot test Google OAuth or a specific employer's live site on your computer. Complete at least one supervised end-to-end dry run (without sending the final application) before relying on the system.
