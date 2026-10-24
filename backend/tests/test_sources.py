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


def test_canonical_job_url_removes_tracking_parameters():
    from app.sources import canonical_job_url, duplicate_key
    a = {"url":"https://example.org/jobs/backend?utm_source=board", "source":"A", "source_id":"1"}
    b = {"url":"https://example.org/jobs/backend?ref=other", "source":"B", "source_id":"2"}
    assert duplicate_key(a) == duplicate_key(b)
    assert canonical_job_url("javascript:alert(1)") == ""


def test_arbeitnow_missing_location_is_not_claimed_to_be_germany():
    from app.sources import fetch_arbeitnow
    class Response:
        def raise_for_status(self): pass
        def json(self):
            return {"data":[{"slug":"a","title":"Backend Engineer",
                             "description":"Python software development",
                             "location":None,"remote":True,"url":"https://example.org/job"}]}
    class Client:
        def get(self,url,params=None):return Response()
    assert fetch_arbeitnow(Client(),pages=1)==[]


def test_jobicy_filters_non_german_or_unknown_remote_locations():
    from app.sources import fetch_jobicy
    class Response:
        def raise_for_status(self): pass
        def json(self):
            def row(i,location):
                return {"id":i,"jobTitle":"Backend Python Engineer","jobDescription":"Python APIs",
                        "companyName":"Employer","jobGeo":location,"url":"https://example.org/job"+str(i)}
            return {"jobs":[row(1,"USA only"),row(2,None),row(3,"Germany"),row(4,"Europe")]}
    class Client:
        def get(self,url,params=None):return Response()
    jobs=fetch_jobicy(Client())
    assert len(jobs)==2
    assert {job["location"] for job in jobs}=={"Germany","Europe"}
