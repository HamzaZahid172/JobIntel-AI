# JobIntel AI — Local Browser Assistant

This is a **local companion** (not a cloud service). It runs headed Chromium on the user's own desktop. The Docker API does not control the employer's browser directly.

## Install on macOS (Node.js 20+)

```bash
cd browser-assistant
npm install
npx playwright install chromium
npm start
```

Keep this terminal running. It listens on **127.0.0.1:3401**, accepts browser requests only from local JobIntel UI origins (localhost:3100 / 127.0.0.1:3100), and stores form data and attachments in memory for the active session. Close the assistant to discard them.

For listings like Arbeitnow → Statista, **Inspect** shows the current listing and an employer-application link. Click **Open Actual Application Form** to open the confirmed Ashby/other employer ATS URL in the controlled Chromium browser. If you manually click the job site's Apply button and it opens an ATS tab, click **Inspect Form** again; the assistant now follows the newer ATS tab.

The assistant detects standard Ashby Name, Email and Phone fields, including hidden résumé file inputs when they have a recognizable label/name. Cookie consent is never accepted automatically. If a custom upload control or other unusual input is not recognized, complete it manually in Chromium. Any unfamiliar site transition must be checked before sharing documents.

Go to JobIntel AI → Job Market / Action Center → **Assisted Apply**. Select up to three files (CV, cover letter, experience/reference letter), review personal details, and start the browser. Chromium appears on the Mac desktop. Use **Fill Known Fields**, **Inspect**, and **Continue** for the steps the worker can recognize. Unrecognized questions, CAPTCHA, sign-in, verification and GDPR consent must be handled by the applicant inside Chromium.

## Submission

The worker NEVER submits until the applicant explicitly enters `SUBMIT` and clicks the approval button. It refuses if no unique final Submit button is found. A click is **not confirmation** of acceptance: inspect the employer's confirmation page, then manually record the application in JobIntel. Do not submit twice if the result is unclear.

Some ATS websites use embedded iframes, browser extensions, complex JS widgets, security challenges or blocked navigation. These may require manual completion; the assistant does not bypass protections or guarantee universal compatibility. Greenhouse public job board read APIs do not confer application POST permissions; this integration uses the employer's **visible application form** rather than privileged ATS credentials.

## Safety

- HTTPS-only employer URLs; localhost/private IPs are blocked as entry URLs
- Binds to `127.0.0.1`, not a network interface; strict UI origin and custom request-header checks
- Attachments restricted to pdf/doc/docx/txt, 8 MB each, 20 MB total, held in memory
- No passwords, salary assertions, authorization answers or GDPR agreements filled automatically
- Manual approval for the final submission; no CAPTCHA bypass; no bulk auto-apply
- Close the session and terminate the server when finished

This is a beta browser-assisted workflow. Test it with employer forms before relying on it, and review all data each time.
