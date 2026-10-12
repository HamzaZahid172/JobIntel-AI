from app.rejection_insights import rejection_review


def test_ommax_reason_reports_only_stated_skills_experience_mismatch():
    body = (
        "Dear Hamza Zahid, thank you for your interest. "
        "After careful consideration, we regret to inform you that we won't "
        "be moving forward with your application. "
        "Your qualifications are beyond question - however, we have come to the "
        "conclusion that your skills and previous experience do not match the "
        "specific requirements of the position. "
        "Due to high volume, we are unable to provide individual feedback."
    )
    result=rejection_review(body,"Your application at OMMAX")
    assert result["category"]=="requirements_or_experience_fit"
    assert "skills and previous experience" in result["evidence"].lower()
    assert "not match" in result["evidence"].lower()
    assert result["individual_feedback_available"] is False
    assert "does not prove" in result["limitations"].lower()
    assert "ATS" in result["limitations"]


def test_generic_rejection_never_invents_detailed_reason():
    result=rejection_review(
        "We regret to inform you that we will not be moving forward with your application.",
        "Your application"
    )
    assert result["category"]=="unspecified"
    assert "did not provide" in result["employer_reason"]
    assert all("lack" not in x for x in result["actions"])


def test_position_filled_is_not_labeled_as_qualification_mismatch():
    result=rejection_review("This role has been filled. Thank you for applying.")
    assert result["category"]=="position_filled"
