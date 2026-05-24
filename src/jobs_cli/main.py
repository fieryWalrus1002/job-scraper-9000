import argparse

from dotenv import load_dotenv

from job_scraper import cli as job_scraper_cli
from prefilter import cli as prefilter_cli


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Scrape job postings and run agents over the pipeline.",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    job_scraper_cli.register(sub)
    prefilter_cli.register(sub)

    args = parser.parse_args()
    args.func(args)
