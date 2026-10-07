from app.match_layer import build_match_report, extract_job_requirements


def test_match_layer_extracts_required_and_preferred_skills():
    description = (
        "Requirements: Python, FastAPI, PostgreSQL and Docker are required. "
        "Experience with REST APIs is required. "
        "Nice to have: Kafka and Airflow."
    )
    req = extract_job_requirements(
        "Backend Software Engineer",
        description,
        "Berlin, Germany",
        False,
    )
    assert "python" in req["required_skills"]
    assert "fastapi" in req["required_skills"]
    assert "kafka" in req["preferred_skills"]
    assert "airflow" in req["preferred_skills"]


def test_match_layer_produces_explainable_breakdown():
    cv = (
        "Senior Software Engineer with 7+ years experience. "
        "Python FastAPI PostgreSQL Docker REST TypeScript JavaScript."
    )
    description = (
        "We require 5+ years of software engineering experience. "
        "Required: Python, FastAPI, PostgreSQL, Docker and REST. "
        "Nice to have: Kafka. English required."
    )
    result = build_match_report(
        cv,
        "Senior Backend Software Engineer",
        description,
        "Berlin, Germany",
        False,
    )
    assert result["overall_score"] >= 70
    assert result["score_breakdown"]["role_alignment"] >= 90
    assert result["score_breakdown"]["required_skills"] >= 80
    assert "kafka" in result["missing_preferred_skills"]
    assert result["eligible_for_preparation"] is True


def test_match_layer_flags_explicit_language_gap():
    cv = "Senior Software Engineer 7+ years Python FastAPI Docker REST."
    description = (
        "Backend Software Engineer. Python FastAPI Docker REST. "
        "Fluent German is required for customer communication."
    )
    result = build_match_report(
        cv,
        "Backend Software Engineer",
        description,
        "Munich, Germany",
        False,
    )
    assert result["language_score"] < 50
    assert result["hard_blockers"]
    assert result["eligible_for_preparation"] is False


def test_match_layer_rejects_german_b2_when_cv_only_has_a2():
    cv = (
        "Senior Software Engineer with 7+ years experience. "
        "Python FastAPI Docker REST. Languages: English C1, German A2."
    )
    description = (
        "Backend Software Engineer. Required: Python FastAPI Docker REST. "
        "German B2 is required for daily team communication."
    )
    result = build_match_report(
        cv,
        "Backend Software Engineer",
        description,
        "Berlin, Germany",
        False,
    )
    assert result["language_score"] < 50
    assert result["hard_blockers"]
    assert result["eligible_for_preparation"] is False
