"""Generate an AI code-review PR comment from a prepared diff file."""

from __future__ import annotations

import argparse
import logging
import pathlib
import sys

from ci.ai_review import (
    AICodeReviewer,
    build_client_from_env,
    fetch_pr_metadata,
    load_pr_metadata_from_file,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
log = logging.getLogger("ai_review_cli")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/ci/ai_code_review.yml")
    parser.add_argument("--prompt", default="prompts/ci/system_prompt_ai_review.md")
    parser.add_argument("--diff-file", default="raw_diff.txt")
    parser.add_argument("--output", default="review.md")
    parser.add_argument("--pr", default=None, help="PR number or URL for gh pr view")
    parser.add_argument(
        "--metadata-file",
        default=None,
        help="JSON file of `gh pr view --json …` output; used instead of "
        "calling gh (the container has no gh). Falls back to --pr if unset.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    diff_path = pathlib.Path(args.diff_file)
    output_path = pathlib.Path(args.output)

    try:
        if not diff_path.exists():
            raise FileNotFoundError(
                f"Input diff file '{args.diff_file}' not found. Did the previous GH Action step fail?"
            )

        git_diff = diff_path.read_text()
        if not git_diff.strip():
            log.info("Input diff is empty; writing empty review output.")
            output_path.write_text("")
            return 0

        client = build_client_from_env(args.config)
        metadata = (
            load_pr_metadata_from_file(args.metadata_file)
            if args.metadata_file
            else fetch_pr_metadata(args.pr)
        )
        reviewer = AICodeReviewer(args.config, args.prompt, client)
        output_path.write_text(reviewer.generate(git_diff, metadata))
        log.info("Review successfully written to %s", output_path)
        return 0
    except Exception:
        log.exception("Critical failure in AI code-review pipeline")
        return 1


if __name__ == "__main__":
    sys.exit(main())
