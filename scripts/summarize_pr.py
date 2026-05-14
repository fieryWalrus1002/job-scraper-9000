import logging
import pathlib
import sys

from ci.summarizer import PRSummarizer

# Professional Logging Configuration
logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
log = logging.getLogger("pr_summarizer_cli")

def main():
    # 1. Define Paths (Relative to Repo Root)
    config_path = "config/ci/pr_summarizer.yml"
    prompt_path = "prompts/ci/system_prompt_pr.md"
    context_file = "context.md"
    output_file = "ai_response.txt"

    try:
        # 2. Check if Context exists (The 'Bronze' data from the GH Action step)
        context_path = pathlib.Path(context_file)
        if not context_path.exists():
            log.error(f"Input file '{context_file}' not found. Did the previous GH Action step fail?")
            sys.exit(1)
        
        git_delta = context_path.read_text()

        # 3. Initialize the 'Silver' Logic layer
        # This will load the .env file automatically via your class's __init__
        summarizer = PRSummarizer(
            config_path=config_path,
            prompt_path=prompt_path
        )

        # 4. Generate the 'Gold' Summary
        log.info("Requesting synthesis from LLM...")
        summary = summarizer.generate(git_delta)

        # 5. Write the Artifact for the 'Voice' step
        pathlib.Path(output_file).write_text(summary)
        log.info(f"Summary successfully written to {output_file}")

    except Exception as e:
        log.error(f"Critical failure in PR Summarization pipeline: {e}")
        # We exit with code 1 so the GitHub Action stops and marks the job as failed
        sys.exit(1)

if __name__ == "__main__":
    main()