# Interview-first application quality release

This release improves decision quality rather than claiming to predict interviews.

## What changed

- Each job is matched against the saved role-specific CV (QA, Data Engineering, Backend) when one exists. Otherwise the latest general CV is used. CV versions belong to their authenticated owner.
- Job Market and Action Center can show the CV file used for matching, rather than presenting a percentage without its source.
- **Pre-Apply Check** explains technical overlap, missing CV evidence, location/language blockers, posting freshness, attachment availability, and items needing human confirmation.
- The ATS and tailoring CV version selectors prefer a CV matching the job family. The candidate can change the selection.
- The same role-specific selection applies to application preparation when the caller does not override it.

## User setup (no paid services)

1. Open **Settings → Private document vault**. Upload a separate, factual, single-column CV for QA Automation, Backend/Python and Data Engineering under the appropriate role-family selector.
2. Verify company names, actual position titles and employment dates against your experience letter. Do not upload the experience letter or private CVs to the public GitHub repository.
3. Make measurable project results clear where evidence exists. Do not claim a skill or number just to raise a match score.
4. Before applying, click **Pre-Apply Check**, select the CV version and review all checks, then verify requirements on the employer's own page.
5. Confirm actual application submission. Track outcomes by job role and CV version, and compare decided outcomes rather than treating pending applications as rejections.

## Important limitations

- Match scores are heuristic CV/job-text overlap and **not** interview, offer or ATS-pass probabilities.
- A job posting date is not evidence that an employer is still accepting applications.
- Work authorization must be verified by the applicant for the specific role and permit. JobIntel never infers unrestricted full-time permission.
- This release does **not** rewrite original encrypted CV attachments or fabricate missing experience. A user must prepare and upload each revised CV.
- Employer submission confirmation and cover-letter content still require human review.
- No external paid API, billing or background job application was introduced.

## Validation

Backend unit tests and frontend CI run in GitHub Actions; run Docker Compose and manual browser smoke testing on the host before relying on this in production.
