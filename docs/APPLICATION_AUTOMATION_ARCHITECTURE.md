# Intelligent Application Engine

This document defines the next automation layer for JobIntel AI. It is an architecture target, not an instruction to submit applications blindly.

## Goal

Turn a strong match into a prepared, reviewable application package and later submit it through provider-specific adapters after user approval.

## Pipeline

```text
current job
   ↓
CV-specific match
   ↓
eligibility rules
   ↓
Ready-to-Apply queue
   ↓
application package
   ├── selected CV
   ├── generated cover letter
   ├── standard profile fields
   ├── screening questions
   └── generated draft answers
   ↓
Review / Approve
   ↓
submission adapter
   ↓
result + audit record
   ↓
My Applications
```

## Proposed backend modules

```text
backend/app/apply_queue.py
backend/app/application_package.py
backend/app/screening_answers.py
backend/app/submission_adapters/
    base.py
    ashby.py
    lever.py
    smartrecruiters.py
    browser.py
```

Each submission adapter should implement a common contract:

```python
class SubmissionAdapter:
    def can_handle(job) -> bool: ...
    def inspect_requirements(job) -> ApplicationRequirements: ...
    def prepare(package) -> PreparedSubmission: ...
    def submit(prepared, approval_token) -> SubmissionResult: ...
```

## Proposed database entities

### apply_queue

- id
- user_id
- live_job_id
- match_score
- eligibility_status
- package_status
- approval_status
- created_at
- updated_at

### application_packages

- id
- user_id
- live_job_id
- cv_profile_id
- cover_letter_file
- screening_answers_json
- validation_json
- created_at

### submission_attempts

- id
- user_id
- live_job_id
- provider
- status
- external_reference
- submitted_at
- error_code
- error_message

## Phase A: automatic preparation

Implement first:

1. user chooses minimum match threshold,
2. jobs passing match + hard filters enter Ready-to-Apply,
3. cover letter is generated,
4. standard profile answers are filled,
5. screening questions are collected when an authorized interface exposes them,
6. JobIntel flags unanswered/high-risk questions,
7. user reviews the package.

No submission occurs automatically in this phase.

## Phase B: one-click approved submission

After Phase A is reliable:

1. user clicks **Approve & Apply**,
2. JobIntel selects an authorized provider adapter,
3. adapter validates all required fields again,
4. application is submitted,
5. result is stored,
6. application CRM status becomes Applied only after confirmed success.

## Phase C: optional rules-based auto-submit

Only after enough successful one-click submissions:

- explicit opt-in
- allowlisted role families
- minimum match threshold
- location/language/work-authorization rules
- duplicate prevention
- daily application limit
- automatic stop on CAPTCHA, unusual consent, ambiguous screening questions or provider errors

The user remains in control of whether automatic submission is enabled.
