# Ingestion Expansion - Third wave

## Job Board APIs to ingest

We've identified these additional job boards we can pillage for jobs.

| Priority | Platform | Implementation Strategy | API Reference / Guide |
| --- | --- | --- | --- |
| **1** | **Workable** | **REST API**: Very developer-friendly; provides structured JSON responses. | [Workable API Ref](https://workable.readme.io/reference) |
| **2** | **BambooHR** | **REST API**: Standard for mid-market; requires an API key per company. | [BambooHR API](https://documentation.bamboohr.com/docs) |
| **3** | **JOIN** | **Webhook/API**: Growing in Europe/Tech; simpler DOM structure if scraping. | [JOIN.com API](https://www.google.com/search?q=https://join.com/api-documentation) |
| **4** | **ADP** | **Partner API**: High complexity; often requires formal "Marketplace" approval. | [ADP Developer Portal](https://developers.adp.com/) |
| **5** | **Workday** | **RPA / Browser Agent**: The "Final Boss." Heavily protected against scrapers. | [Workday API (Requires Auth)](https://community.workday.com/sites/default/files/file-hosting/restapi/index.html) |

---

### Things to keep in mind:

1. **The "Workday" Problem**: Workday does not want to be scraped. We may need to create a **Browser Extension (RPA)** workaround.
2. **Cost-Efficiency**: Use an **Azure Logic App** or **ADF Trigger** to run these once a day. Do not keep a container running 24/7 for a job that only changes every 24 hours.

```markdown
# Engineering Standards: Job Ingestion Pipeline

Where does it end up after raw?

## Success Criteria
- **Source Fidelity**: Raw JSON/HTML must be saved to `bronze/job-data/{vendor}/{timestamp}.json`.