"""Application conversion analytics: observed states, not predicted outcomes."""
import re
from datetime import date
from collections import defaultdict
from urllib.parse import urlparse


def role_family(role: str) -> str:
    title=(role or "").lower()
    if re.search(r"\b(qa|quality assurance|sdet|test engineer|automation tester|test automation)\b",title):
        return "QA Automation"
    if re.search(r"\b(data engineer|etl|data analyst|data infrastructure|analytics engineer)\b",title):
        return "Data Engineering"
    if re.search(r"\b(ai engineer|machine learning|ml engineer|llm)\b",title):
        return "AI Engineering"
    if re.search(r"\b(backend|back.end|fullstack|full.stack|software engineer|python developer)\b",title):
        return "Backend / Software"
    return "Other"


def application_analytics(applications, *, today: date | None = None) -> dict:
    today = today or date.today()
    groups=defaultdict(list)
    sources=defaultdict(list)
    cvs=defaultdict(list)
    total=len(applications)
    final_interviews={"Interview","Final","Offer"}
    for app in applications:
        groups[role_family(app.role)].append(app)
        try:
            host=(urlparse(app.url).hostname or "").lower()
            if host.startswith("www."):host=host[4:]
            source=host if host else "Unknown"
        except ValueError:
            source="Unknown"
        sources[source].append(app)
        cvs[(app.cv_version or "Unspecified")].append(app)

    def has_submission_reference(entry):
        """Tracking notes may document proof; lack of notes is NOT failure."""
        return bool(re.search(
            r"(?:confirmation (?:number|id|email)|application received|"
            r"submission confirmed|successfully submitted|application submitted)",
            getattr(entry, "notes", "") or "", re.I,
        ))

    review = {
        "applications_without_cv_version": sum(
            1 for a in applications if (getattr(a, "cv_version", "") or "").strip().lower()
            in {"", "current cv", "unspecified"}
        ),
        "applications_without_source_url": sum(
            1 for a in applications if not (getattr(a, "url", "") or "").strip()
        ),
        "applications_without_documented_submission_confirmation": sum(
            1 for a in applications if a.status in {"Applied", "Screening", "Rejected"}
            and not has_submission_reference(a)
        ),
        "pending_over_14_days": sum(
            1 for a in applications if a.status in {"Applied", "Screening"}
            and getattr(a, "applied_date", None) is not None
            and (today - a.applied_date).days >= 14
        ),
        "note": "Missing confirmation in the tracker does not mean the employer failed to receive an application.",
    }

    def summarize(entries):
        n=len(entries)
        interviews=sum(1 for a in entries if a.status in final_interviews)
        rejections=sum(1 for a in entries if a.status=="Rejected")
        offers=sum(1 for a in entries if a.status=="Offer")
        pending=sum(1 for a in entries if a.status in {"Applied","Screening"})
        no_response=sum(1 for a in entries if a.status in {"Applied","Screening"})
        needs_review=bool(n >= 10 and interviews == 0)

        decided=interviews+rejections
        return {
            "pending_or_screening":pending,
            "awaiting_outcome":no_response,
            "zero_interview_diagnostic":needs_review,
            "diagnostic":"Review eligibility, CV targeting, and submission confirmation; no single cause can be inferred." if needs_review else None,
            "decided_outcomes":decided,
            "decided_interview_conversion_percent":round(100*interviews/decided,1) if decided else None,
            "applications":n,"interviews_or_later":interviews,
            "rejected":rejections,"offers":offers,
            "interview_conversion_percent":round(100*interviews/n,1) if n else 0,
            "sample_warning":n<30 or decided<10,
        }
    return {
        "total_applications":total,
        "application_quality_audit":review,
        "overall":summarize(applications),
        "by_role":{k:summarize(v) for k,v in sorted(groups.items())},
        "by_source":{k:summarize(v) for k,v in sorted(sources.items())},
        "by_cv_version":{k:summarize(v) for k,v in sorted(cvs.items())},
        "interpretation": (
            "Early directional signals only: fewer than 30 applications. "
            "Rejections rarely prove a specific CV defect or ATS failure."
            if total<30 else
            "Observed tracker outcomes, not employer hiring probabilities."
        ),
        "notes":"Interview conversion counts Interview, Final and Offer among tracked applications. Pending does not mean rejected. Decided outcomes are a limited subset, not an estimate of hiring probability.",
    }
