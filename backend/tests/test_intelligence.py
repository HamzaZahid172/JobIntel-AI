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
