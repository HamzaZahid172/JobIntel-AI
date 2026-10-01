from types import SimpleNamespace

from app.ats_collectors import fetch_ashby


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.last_url = None
        self.last_params = None

    def get(self, url, params=None, headers=None):
        self.last_url = url
        self.last_params = params
        return FakeResponse(self.payload)


def test_ashby_collector_keeps_germany_technical_jobs_and_public_listings():
    payload = {
        "apiVersion": "1",
        "jobs": [
            {
                "title": "Senior Backend Software Engineer",
                "location": "Berlin, Germany",
                "isListed": True,
                "isRemote": False,
                "workplaceType": "Hybrid",
                "descriptionPlain": "Build Python FastAPI services with PostgreSQL and Docker.",
                "publishedAt": "2026-10-01T10:00:00+00:00",
                "employmentType": "FullTime",
                "jobUrl": "https://jobs.ashbyhq.com/example/job-1",
                "applyUrl": "https://jobs.ashbyhq.com/example/job-1/application",
                "address": {"postalAddress": {"addressLocality": "Berlin", "addressCountry": "Germany"}},
            },
            {
                "title": "Account Executive",
                "location": "Berlin, Germany",
                "isListed": True,
                "isRemote": False,
                "descriptionPlain": "Sell software to enterprise customers.",
                "jobUrl": "https://jobs.ashbyhq.com/example/job-2",
            },
            {
                "title": "Senior Python Engineer",
                "location": "Paris, France",
                "isListed": True,
                "isRemote": False,
                "descriptionPlain": "Python backend engineering.",
                "jobUrl": "https://jobs.ashbyhq.com/example/job-3",
            },
            {
                "title": "QA Automation Engineer",
                "location": "Remote Europe",
                "isListed": False,
                "isRemote": True,
                "descriptionPlain": "Playwright TypeScript test automation.",
                "jobUrl": "https://jobs.ashbyhq.com/example/job-4",
            },
        ],
    }
    client = FakeClient(payload)
    target = SimpleNamespace(identifier="Example", label="Example GmbH")

    jobs = fetch_ashby(client, target)

    assert client.last_url.endswith("/posting-api/job-board/Example")
    assert client.last_params == {"includeCompensation": "false"}
    assert len(jobs) == 1
    assert jobs[0]["source"] == "Ashby"
    assert jobs[0]["company"] == "Example GmbH"
    assert jobs[0]["title"] == "Senior Backend Software Engineer"
    assert jobs[0]["url"].endswith("/application")
    assert "python" in jobs[0]["skills"]
