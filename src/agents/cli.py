import argparse
import logging
import os
import yaml

from dotenv import load_dotenv

from agents.remote_filter.cli import add_subcommands as add_remote_filter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

def load_remote_config(path: str) -> dict:
    with open(path, 'r') as f:
        # 1. Read raw text
        content = f.read()
        
        # 2. Expand environment variables (converts ${HOME_LOCATION} to "Pullman, WA")
        expanded_content = os.path.expandvars(content)
        
        # 3. Parse the expanded string as YAML
        return yaml.safe_load(expanded_content)

    # # Usage
    # config = load_remote_config("config/remote_agent.yml")
    # print(config['policy_thresholds']['local_exceptions']['target_city']) 
    # # Output: Pullman

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
