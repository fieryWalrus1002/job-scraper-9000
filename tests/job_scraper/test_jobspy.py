import sys
from types import SimpleNamespace

from job_scraper.scrapers.jobspy import JobSpyQuery, JobSpyScraper


class FakeJobSpyResult:
    def __init__(self, rows):
        self.rows = rows

    def iterrows(self):
        yield from enumerate(self.rows)


def test_jobspy_description_html_is_cleaned_to_markdown_and_scrubbed(monkeypatch):
    def fake_scrape_jobs(**_kwargs):
        return FakeJobSpyResult(
            [
                {
                    "site": "indeed",
                    "job_url": "https://example.test/jobs/123",
                    "title": "Data Engineer",
                    "company": "Acme",
                    "location": "Remote, USA",
                    "date_posted": "2024-01-15",
                    "description": """
                    &lt;p&gt;&lt;strong&gt;Responsibilities&lt;/strong&gt;&lt;/p&gt;
                    &lt;ul&gt;&lt;li&gt;Build Python services&lt;/li&gt;&lt;/ul&gt;
                    &lt;p&gt;Email hiring@example.com.&lt;/p&gt;
                    """,
                }
            ]
        )

    monkeypatch.setitem(
        sys.modules, "jobspy", SimpleNamespace(scrape_jobs=fake_scrape_jobs)
    )

    query = JobSpyQuery(search_term="data engineer", site_name=["indeed"])

    [job] = JobSpyScraper(query).scrape()

    assert "**Responsibilities**" in job.description
    assert "- Build Python services" in job.description
    assert "hiring@example.com" not in job.description
    assert "[EMAIL_REDACTED]" in job.description
    assert "&lt;" not in job.description
    assert "<li>" not in job.description
    assert job.scrub_counts == {"email": 1, "phone": 0}
