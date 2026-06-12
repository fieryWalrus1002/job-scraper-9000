import argparse

from dotenv import load_dotenv

from agents.remote_filter import cli as remote_filter_cli
from agents.skills_fit import cli as skills_fit_cli
from job_scraper import cli as job_scraper_cli
from prefilter import cli as prefilter_cli
from ingest import cli as ingest_cli
from pipeline import overnight as overnight_cli


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Scrape job postings and run agents over the pipeline.",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    job_scraper_cli.register(sub)
    prefilter_cli.register(sub)
    remote_filter_cli.register(sub)
    skills_fit_cli.register(sub)
    ingest_cli.register(sub)
    overnight_cli.register(sub)

    args = parser.parse_args()
    args.func(args)
