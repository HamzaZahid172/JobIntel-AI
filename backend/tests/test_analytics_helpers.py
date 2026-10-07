from datetime import datetime
from types import SimpleNamespace

from app.main import application_conversion_insights, build_skill_gap, build_source_analytics


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return self.rows


class FakeDB:
    def __init__(self, targets):
        self.targets = targets

    def query(self, model):
        return FakeQuery(self.targets)


def test_source_analytics_lists_supported_sources_even_with_zero_jobs():
    targets = [
        SimpleNamespace(provider="ashby", enabled=True),
    ]
    jobs = [
        SimpleNamespace(
            source="Arbeitnow",
            fetched_at=datetime(2026, 10, 1, 10, 0, 0),
        ),
        SimpleNamespace(
            source="Ashby",
            fetched_at=datetime(2026, 10, 1, 11, 0, 0),
        ),
    ]
    rows = build_source_analytics(FakeDB(targets), 1, jobs, jobs)
    by_source = {row["source"]: row for row in rows}

    assert set(["Arbeitnow", "Jobicy", "Ashby", "Lever", "SmartRecruiters", "Greenhouse"]).issubset(by_source)
    assert by_source["Ashby"]["status"] == "configured"
    assert by_source["Ashby"]["jobs"] == 1
    assert by_source["Lever"]["status"] == "not configured"
    assert by_source["Lever"]["jobs"] == 0


def test_skill_gap_uses_structured_required_and_preferred_requirements():
    cv = SimpleNamespace(
        text="Senior Backend Software Engineer 7+ years Python FastAPI Docker REST."
    )
    jobs = [
        SimpleNamespace(
            title="Backend Software Engineer",
            description=(
                "Required: Python FastAPI Docker REST Kafka. "
                "Nice to have: Airflow."
            ),
            location="Berlin, Germany",
            remote=False,
        ),
        SimpleNamespace(
            title="Senior Backend Engineer",
            description=(
                "Requirements: Python FastAPI Docker Kafka. "
                "Preferred: Terraform."
            ),
            location="Munich, Germany",
            remote=False,
        ),
    ]

    gaps = build_skill_gap(cv, jobs)
    by_skill = {row["skill"].lower(): row for row in gaps}

    assert by_skill["kafka"]["required_count"] == 2
    assert by_skill["airflow"]["preferred_count"] == 1
    assert by_skill["terraform"]["preferred_count"] == 1


def test_application_conversion_insights_flags_high_match_rejections():
    apps = [
        SimpleNamespace(status="Rejected", match_score=88),
        SimpleNamespace(status="Rejected", match_score=82),
        SimpleNamespace(status="Applied", match_score=91),
        SimpleNamespace(status="Applied", match_score=86),
        SimpleNamespace(status="Applied", match_score=80),
        SimpleNamespace(status="Rejected", match_score=70),
    ]
    result = application_conversion_insights(apps)
    assert result["submitted"] == 6
    assert result["positive_response_rate"] == 0
    assert result["high_match_rejections"] == 2
    assert result["rejection_rate"] == 50
    assert any("positioning problem" in item for item in result["recommendations"])
