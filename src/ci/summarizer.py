import os
import pathlib
import logging
import yaml
from openai import OpenAI
from dotenv import load_dotenv

log = logging.getLogger(__name__)


class PRSummarizer:
    def __init__(
        self,
        config_path: str,
        prompt_path: str,
        client: OpenAI,
    ):
        self.config = self._load_config(config_path)
        self.system_prompt = self._load_and_strip_prompt(prompt_path)
        self.client = client

    def _load_config(self, path: str) -> dict:
        return yaml.safe_load(pathlib.Path(path).read_text())

    def _load_and_strip_prompt(self, path: str) -> str:
        content = pathlib.Path(path).read_text()
        if content.startswith("---"):
            parts = content.split("---")
            if len(parts) >= 3:
                content = "---".join(parts[2:])
        return content.strip()

    def generate(self, git_diff: str) -> str:
        log.info("Generating PR summary using model: %s", self.config["llm"]["model"])
        try:
            response = self.client.chat.completions.create(
                model=self.config["llm"]["model"],
                temperature=self.config["llm"]["temperature"],
                max_tokens=self.config["llm"]["max_tokens"],
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {
                        "role": "user",
                        "content": f"Please summarize the following git delta:\n\n{git_diff}",
                    },
                ],
            )
            if not response.choices or not response.choices[0].message.content:
                raise ValueError("Received empty response from OpenAI API.")
            log.info("Successfully generated PR summary.")
            return response.choices[0].message.content.strip()
        except Exception as e:
            log.error("Failed to generate AI summary: %s", e)
            raise


def build_client_from_env(config_path: str) -> OpenAI:
    """Build an OpenAI-compatible client.

    Provider, model, and Ollama URL come from the YAML config (non-secrets).
    Only OPENAI_API_KEY is read from the environment.
    """
    load_dotenv()
    config = yaml.safe_load(pathlib.Path(config_path).read_text())
    provider = config["llm"].get("provider", "openai").lower()

    if provider == "ollama":
        base_url = config["llm"].get("ollama_base_url", "http://localhost:11434/v1")
        return OpenAI(base_url=base_url, api_key="ollama")

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable is required.")
    return OpenAI(api_key=api_key)
