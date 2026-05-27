# Ingestion Expansion

## Job Board API Priority

| Priority | Platform | Strategy                                                                          |
| -------- | -------- | --------------------------------------------------------------------------------- |
| 1        | Workable | REST API — developer-friendly, structured JSON, no auth for public listings       |
| 2        | BambooHR | REST API — mid-market standard, per-company API key required                      |
| 3        | JOIN.com | Webhook/API or simple DOM — growing in EU/tech                                    |
| 4        | ADP      | Partner API — high complexity, requires Marketplace approval                      |
| 5        | Workday  | **RPA / Browser Agent** — heavily anti-scrape; treat as a separate RPA workstream |

## Notes

- **The Workday Problem**: Workday actively blocks scrapers. A browser extension or RPA approach is likely required. Do not attempt a raw HTTP scraper.
- **Cost efficiency**: Run ingestion once daily via a scheduled job (Azure Container App Job or Logic App). No persistent container needed.

Work tracked on GitHub — `gh issue list` or <https://github.com/fieryWalrus1002/job-scraper-9000/issues>
