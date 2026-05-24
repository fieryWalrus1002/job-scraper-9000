import argparse

from dotenv import load_dotenv

from job_scraper.cli import (
    _add_linkedin,
    _add_jobspy,
    _add_greenhouse,
    _add_lever,
    _add_ashby,
    _add_sel,
    _add_discover,
    _add_prefilter,
    _add_remote_filter,
    _add_skills_fit,
    _add_run_config,
)


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Scrape job postings and run agents over the pipeline.",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    _add_linkedin(sub)
    _add_jobspy(sub)
    _add_greenhouse(sub)
    _add_lever(sub)
    _add_ashby(sub)
    _add_sel(sub)
    _add_discover(sub)
    _add_prefilter(sub)
    _add_remote_filter(sub)
    _add_skills_fit(sub)
    _add_run_config(sub)

    args = parser.parse_args()
    args.func(args)
