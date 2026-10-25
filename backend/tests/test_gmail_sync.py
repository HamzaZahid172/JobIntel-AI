from app.gmail_sync import _gmail_message_query, classify_message, match_application
from app.models import Application


def test_classify_rejection_email():
    assert (
        classify_message(
            "Update on your application",
            "Unfortunately, we have decided not to move forward with your application.",
        )
        == "Rejected"
    )


def test_classify_interview_email():
    assert (
        classify_message(
            "Interview invitation - Backend Engineer",
            "We would like to schedule a call with the hiring manager.",
        )
        == "Interview"
    )


def test_match_application_prefers_company_and_role():
    applications = [
        Application(
            id=1,
            user_id=1,
            company="Example GmbH",
            role="Backend Python Engineer",
            status="Applied",
        ),
        Application(
            id=2,
            user_id=1,
            company="Another AG",
            role="QA Automation Engineer",
            status="Applied",
        ),
    ]

    matched = match_application(
        applications,
        "Example - Backend Python Engineer application update",
        "jobs@example.com",
        "Thank you for your application.",
    )

    assert matched is not None
    assert matched.id == 1


def test_unrelated_email_is_not_matched():
    applications = [
        Application(
            id=1,
            user_id=1,
            company="Example GmbH",
            role="Backend Python Engineer",
            status="Applied",
        )
    ]

    assert (
        match_application(
            applications,
            "Your monthly electricity bill",
            "billing@utility.test",
            "Your statement is ready.",
        )
        is None
    )



def test_gmail_query_includes_trash_but_excludes_spam():
    query = _gmail_message_query(45)
    assert "in:anywhere" in query
    assert "-in:spam" in query
    assert "newer_than:45d" in query


def test_shift_technology_decision_to_move_forward_with_candidates_is_rejection():
    subject = "Thank you for your application at Shift Technology"
    body = (
        "Hi Hamza, Thank you for your application for the Data & AI Engineer "
        "Intern (6 months) position at Shift Technology. "
        "After reviewing your work and experience, we've made the decision "
        "to move forward with candidates who more closely align with our "
        "current needs for this position."
    )
    assert classify_message(subject, body) == "Rejected"


def test_shifttechnology_company_alias_matches_shift_technology_sender():
    apps = [
        Application(id=31, user_id=2, company="shifttechnology",
                    role="Data & AI Engineer Intern (6 months)", status="Applied"),
        Application(id=32, user_id=2, company="Another Ltd",
                    role="Data Engineer", status="Applied"),
    ]
    matched = match_application(
        apps, "Thank you for your application at Shift Technology",
        "no_reply@shift-technology.com",
        "Thank you for your application for the Data & AI Engineer Intern "
        "(6 months) position at Shift Technology. After reviewing your work "
        "and experience, we've made the decision to move forward with candidates.",
    )
    assert matched is not None
    assert matched.id == 31


def test_company_alias_still_refuses_ambiguous_multiple_applications():
    apps = [
        Application(id=41, user_id=2, company="shifttechnology",
                    role="Data & AI Engineer Intern", status="Applied"),
        Application(id=42, user_id=2, company="Shift Technology",
                    role="Data & AI Engineer Intern", status="Applied"),
    ]
    assert match_application(
        apps, "Thank you for your application at Shift Technology",
        "no_reply@shift-technology.com",
        "Data & AI Engineer Intern decision",
    ) is None


def test_rejection_without_explicit_decision_not_auto_rejected():
    assert classify_message(
        "Thank you for your application at Shift Technology",
        "We are reviewing your work and experience alongside other candidates."
    ) != "Rejected"
