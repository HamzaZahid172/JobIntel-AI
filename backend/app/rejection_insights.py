"""Evidence-grounded rejection review; no invented personal ATS decisions."""
import re


def rejection_review(body: str, subject: str = "") -> dict:
    text = re.sub(r"\s+", " ", body or "").strip()
    lowered = text.casefold().replace("’", "'")
    mismatch = (
        "skills and previous experience do not match",
        "skills and experience do not match",
        "experience does not match",
        "profile does not match",
        "not meet the requirements",
        "not meet our requirements",
        "does not meet the requirements",
        "not the right fit",
    )
    if any(phrase in lowered for phrase in mismatch):
        category = "requirements_or_experience_fit"
        reason = "The employer says your experience or skills did not align with the position's requirements."
        terms = ["skills and previous experience", "experience does not match", "profile does not match", "requirements", "right fit"]
    elif "position has been filled" in lowered or "role has been filled" in lowered:
        category = "position_filled"
        reason = "The employer says this position has been filled."
        terms = ["position has been filled", "role has been filled"]
    else:
        category = "unspecified"
        reason = "The employer rejected the application but did not provide a specific, verifiable reason."
        terms = ["regret to inform", "not moving forward", "won't be moving forward"]

    evidence = ""
    for term in terms:
        ix = lowered.find(term)
        if ix >= 0:
            # Include enough context for a meaningful sentence while limiting
            # what is returned to the browser. Keep the original text intact.
            start = max(0, text.rfind(".", 0, ix) + 1)
            end = text.find(".", ix)
            end = min(len(text), end + 1) if end >= 0 else min(len(text), ix + 250)
            evidence = text[start:end].strip()[:400]
            break
    no_individual_feedback = any(phrase in lowered for phrase in (
        "unable to provide individual feedback", "unable to provide individualized feedback",
        "cannot provide individual feedback", "unable to give individual feedback",
    ))
    actions = [
        "Compare the saved job requirements with the exact CV version you submitted; identify only demonstrable gaps.",
        "For the next suitable vacancy, highlight relevant projects and outcomes truthfully in the first half of the CV.",
        "Prioritize roles where required skills, seniority, employment type and German-language expectations are a strong fit.",
    ]
    if no_individual_feedback:
        actions.append("This employer explicitly says it cannot provide individual feedback; do not treat the generic message as a detailed assessment.")
    return {
        "category": category,
        "employer_reason": reason,
        "evidence": evidence,
        "individual_feedback_available": not no_individual_feedback,
        "limitations": "This reflects only the employer's wording. It does not prove an ATS failure, an incorrect CV, or a specific missing skill.",
        "actions": actions,
        "source_subject": subject[:200],
    }
