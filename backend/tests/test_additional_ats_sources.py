from types import SimpleNamespace

from app.ats_collectors import fetch_personio, fetch_workable, _safe_board_slug


def target(slug, provider):
    return SimpleNamespace(identifier=slug,label="Example Employer",provider=provider)


class FakeResponse:
    def __init__(self,payload,xml=False):
        self.payload=payload
        self.content=payload if xml else b""
    def raise_for_status(self):
        pass
    def json(self):
        return self.payload


def test_personio_public_xml_extracts_only_germany_technical_jobs():
    body=b"""<?xml version="1.0"?>
    <workzag>
    <position><id>123</id><name>Python Backend Engineer</name>
       <office>Berlin</office><employmentType>permanent</employmentType>
       <createdAt>2026-10-12</createdAt>
       <jobDescriptions><jobDescription><name>Tasks</name>
       <value><![CDATA[<p>Develop Python FastAPI APIs</p>]]></value></jobDescription></jobDescriptions>
    </position>
    <position><id>124</id><name>Sales Manager</name><office>New York</office></position>
    </workzag>"""
    class Client:
        def get(self,url,params=None,headers=None):
            assert url=="https://example.jobs.personio.de/xml"
            assert params=={"language":"en"}
            return FakeResponse(body,xml=True)
    jobs=fetch_personio(Client(),target("example","personio"))
    assert len(jobs)==1
    assert jobs[0]["source"]=="Personio"
    assert "Python" in jobs[0]["description"]
    assert jobs[0]["url"]=="https://example.jobs.personio.de/job/123"


def test_workable_public_feed_excludes_non_target_locations():
    payload={"jobs":[
        {"shortcode":"A1","title":"QA Automation Engineer",
         "description":"Cypress API tests","city":"Berlin","country":"Germany",
         "url":"https://apply.workable.com/example/j/A1/","employment_type":"Full-time"},
        {"shortcode":"B2","title":"Backend Engineer","description":"Python",
         "city":"Austin","country":"USA"}
    ]}
    class Client:
        def get(self,url,params=None,headers=None):
            assert url=="https://www.workable.com/api/accounts/example"
            return FakeResponse(payload)
    jobs=fetch_workable(Client(),target("example","workable"))
    assert len(jobs)==1
    assert jobs[0]["source"]=="Workable"
    assert jobs[0]["source_id"]=="example:A1"


def test_untrusted_employer_slug_is_rejected():
    for invalid in ("https://evil.test", "../data", "foo/bar", ".hidden"):
        try:
            _safe_board_slug(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("Unexpectedly trusted identifier: "+invalid)
