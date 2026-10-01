# Match Layer and Application Preparation Layer

## Match Layer

The match layer converts the uploaded CV and a normalized job into an explainable match report.

### Inputs

- latest uploaded CV text
- job title
- full normalized job description
- job location
- remote flag

### Requirement extraction

JobIntel separates job skills into:

- **required/core skills**: skills in requirements/qualification language or normal job requirements
- **preferred skills**: skills in phrases such as "nice to have", "preferred", "bonus" or "plus"
- **role family**
- **years of experience** when explicitly stated
- **explicit language requirements**
- **location / remote signal**

### Score breakdown

The current v0.7 score is decision support, not an interview probability:

```text
Role alignment          30%
Required skills         30%
Preferred skills        10%
Experience              15%
Language                10%
Location                 5%
                       ----
                        100%
```

The match report also exposes:

- matched required skills
- missing required skills
- matched preferred skills
- missing preferred skills
- role families
- hard blockers
- human-readable reasons
- whether the job is eligible for application preparation

Hard blockers currently include:

- strong role-family mismatch
- very low core-skill coverage
- an explicit required language not evidenced in the uploaded CV

A high score alone does not submit anything.

### API

```http
GET /api/jobs/{job_id}/match-report
```

Job Market and Matches also receive the score breakdown in normal job responses.

---

## Application Preparation Layer

The preparation layer creates a persistent application package for one job and the current CV.

### Flow

```text
selected job
    +
latest CV
    ↓
structured match report
    ↓
cover-letter generation
    ↓
safe screening-answer drafts
    ↓
validation
    ↓
persistent ApplicationPackage
    ↓
Application Prep page
```

### What is prepared automatically

- snapshot of job/company/source/application URL
- CV profile reference and filename
- structured match report
- CV-grounded cover letter
- draft answers for:
  - why this role
  - relevant experience
- validation checks

### What is deliberately left for user input

JobIntel does not invent answers for facts that are not safely present in the CV/profile:

- work authorization / visa status
- salary expectation
- start date / notice period
- language proficiency when no clear evidence exists

Those fields are marked **needs_user_input** on the Application Prep page.

### Package states

```text
Needs Review
    ↓ user completes unresolved fields
Package Ready
```

"Package Ready" means the preparation checks passed. It does **not** mean the application was submitted.

### APIs

```http
POST  /api/jobs/{job_id}/prepare-application
GET   /api/application-packages
GET   /api/application-packages/{package_id}
PATCH /api/application-packages/{package_id}/answers
POST  /api/application-packages/{package_id}/cover-letter
```

### UI

Job Market and Matches now expose:

```text
Apply on source
Create cover letter
Prepare application
Track application
```

The sidebar includes **Application Prep**, where prepared packages can be reviewed, answers can be completed, and the prepared cover letter can be downloaded.

---

## Where this fits in the full architecture

```text
Collection Layer
  Arbeitnow / Jobicy / Lever / SmartRecruiters / Ashby / imports
        ↓
Normalization + PostgreSQL
        ↓
Match Layer
  requirements + role + skills + experience + language + location
        ↓
Application Preparation Layer
  CV + match + cover letter + screening drafts + validation
        ↓
Human Review / Approval
        ↓
Future Submission Layer
  authorized ATS API or permitted employer-site automation
        ↓
Application CRM
```
