#!/usr/bin/env python3
"""Run the remote_filter agent over raw jobs into one classified output."""

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from agents.remote_filter.runner import (  # noqa: E402
    DEFAULT_CLASSIFIED_PATH,
    DEFAULT_CONFIG_PATH,
    DEFAULT_INPUT_DIR,
    run_remote_filter,
)

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> None:
    try:
        run_remote_filter(
            input_path=DEFAULT_INPUT_DIR,
            classified_path=DEFAULT_CLASSIFIED_PATH,
            config_path=DEFAULT_CONFIG_PATH,
            user_timezone=os.environ.get("USER_TIMEZONE"),
        )
    except FileNotFoundError as exc:
        logging.getLogger(__name__).error(str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
