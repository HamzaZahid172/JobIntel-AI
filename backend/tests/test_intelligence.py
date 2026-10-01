from app.intelligence import ats_check, match_cv_to_job

def test_ats_check_scores_structured_cv():
    text = "Email me@example.com +49 123456789 Experience Python SQL AWS Docker Kubernetes Skills Projects Education\n- Built APIs\n- Built pipelines\n- Automated tests\n- Improved CI\n- Led team\n- Shipped platform " + ("word " * 400)
    result = ats_check(text)
    assert result["score"] >= 80
    assert result["status"] == "ATS Ready"

def test_match_detects_missing_skills():
    r = match_cv_to_job("Senior engineer 7+ years Python SQL Docker AWS", "Python SQL Docker AWS Kafka Airflow")
    assert "kafka" in r["missing_skills"]
    assert "python" in r["matched_skills"]


from app.intelligence import is_target_technical_role, rank_cv_skills


def test_cv_primary_languages_rank_first():
    cv = (
        "Senior Software Engineer Python Python Python TypeScript TypeScript "
        "JavaScript JavaScript Playwright Playwright Cypress Selenium REST APIs "
        "Data Engineering Backend Automation Engineer"
    )
    ranked = [row["skill"] for row in rank_cv_skills(cv, limit=4)]
    assert ranked[:3] == ["python", "typescript", "javascript"]


def test_sales_role_is_not_high_match_from_generic_technical_words():
    cv = "Senior Software Engineer 7+ years Python TypeScript JavaScript REST FastAPI"
    result = match_cv_to_job(
        cv,
        "Work with advertiser APIs, data dashboards and REST integrations.",
        "Mid-Market Account Executive - Advertiser",
    )
    assert result["role_score"] < 30
    assert result["overall_score"] <= 45


def test_backend_role_gets_role_alignment():
    cv = "Senior Software Engineer 7+ years Python TypeScript JavaScript FastAPI REST Docker"
    result = match_cv_to_job(
        cv,
        "Build Python FastAPI REST services with Docker and PostgreSQL.",
        "Senior Backend Software Engineer",
    )
    assert result["role_score"] >= 90
    assert result["overall_score"] >= 65


def test_title_first_filter_excludes_nontechnical_account_role():
    assert not is_target_technical_role(
        "Account Manager - Advertiser",
        "Our platform uses APIs, data and cloud technology.",
    )
    assert is_target_technical_role(
        "QA Automation Engineer",
        "Build Playwright and TypeScript test automation.",
    )
