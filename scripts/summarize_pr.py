import logging
import pathlib
import sys

from ci.summarizer import PRSummarizer, build_client_from_env

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
log = logging.getLogger("pr_summarizer_cli")


def main():
    config_path = "config/ci/pr_summarizer.yml"
    prompt_path = "prompts/ci/system_prompt_pr.md"
    context_file = "context.md"
    output_file = "ai_response.txt"

    try:
        context_path = pathlib.Path(context_file)
        if not context_path.exists():
            log.error("Input file '%s' not found. Did the previous GH Action step fail?", context_file)
            sys.exit(1)

        git_delta = context_path.read_text()
        client = build_client_from_env(config_path)
        summarizer = PRSummarizer(config_path, prompt_path, client)
        summary = summarizer.generate(git_delta)
        pathlib.Path(output_file).write_text(summary)
        log.info("Summary successfully written to %s", output_file)

    except Exception as e:
        log.error("Critical failure in PR Summarization pipeline: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
