# Justfile
# Call it like this: just pipeline DATE=2026-05-27

# Default to today's date using backticks, but customizable
DATE := `date +%F`

scrape:
    uv run job-scraper-9000 run-config config/search.yml --save --run-date {{DATE}}

prefilter:
    uv run job-scraper-9000 prefilter --run-date {{DATE}}

filter-remote:
    uv run job-scraper-9000 remote-filter --run-date {{DATE}}

filter-skills:
    uv run job-scraper-9000 skills-fit --run-date {{DATE}}

pipeline:
    just scrape
    just prefilter
    just filter-remote
    just filter-skills
