import argparse
import logging

from dotenv import load_dotenv

from agents.remote_filter.cli import add_subcommands as add_remote_filter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(
        prog="agents",
        description="Job-scraper-9000 processing agents — filter, score, and dispatch job postings.",
    )
    sub = parser.add_subparsers(dest="agent", metavar="AGENT")
    sub.required = True

    add_remote_filter(sub)
    # Future agents registered here:
    # add_scorer(sub)
    # add_dispatcher(sub)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
