from app.sources import germany_relevant, relevant_role, strip_html


def test_strip_html():
    assert strip_html("<p>Python &amp; SQL</p>") == "Python & SQL"


def test_relevant_tech_role():
    assert relevant_role("Senior Data Engineer", "Python and Kafka")
    assert not relevant_role("Retail Store Manager", "Manage store operations")


def test_germany_location_filter():
    assert germany_relevant("Berlin, Germany", False)
    assert not germany_relevant("Remote", True, "https://www.arbeitnow.com/jobs/x")
    assert not germany_relevant("Paris, France", False)


def test_remote_location_must_confirm_germany():
    assert not germany_relevant("Remote", True, "https://example.com/jobs/1")
    assert not germany_relevant("USA only", True, "https://example.com/jobs/2")
    assert germany_relevant("Remote - Germany", True, "https://example.com/jobs/3")
