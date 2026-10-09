from app.gmail_sync import classify_message, match_application
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
