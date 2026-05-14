import os
import pathlib
import yaml
import logging
from openai import OpenAI
from dotenv import load_dotenv

log = logging.getLogger(__name__)


class PRSummarizer:
    def __init__(self, config_path: str, prompt_path: str):
        load_dotenv()

        self.config = self._load_config(config_path)
        self.system_prompt = self._load_and_strip_prompt(prompt_path)

        # Allow LLM_MODEL env var to override the model in config
        model_override = os.environ.get("LLM_MODEL")
        if model_override:
            self.config["llm"]["model"] = model_override

        provider = os.environ.get("LLM_PROVIDER", "openai").lower()
        if provider == "ollama":
            base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
            self.client = OpenAI(base_url=base_url, api_key="ollama")
        else:
            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY environment variable is required.")
            self.client = OpenAI(api_key=api_key)
        
    def _load_config(self, path: str) -> dict:
        """Loads operational parameters from YAML."""
        return yaml.safe_load(pathlib.Path(path).read_text())

    def _load_and_strip_prompt(self, path: str) -> str:
        """Extracts instructions from Markdown, ignoring frontmatter metadata."""
        content = pathlib.Path(path).read_text()
        if content.startswith("---"):
            # Splits by '---', takes the 3rd part (index 2)
            parts = content.split("---")
            if len(parts) >= 3:
                content = "---".join(parts[2:])
        return content.strip()

    def generate(self, git_diff: str) -> str:
        """
        Executes the LLM call using the 'Plumbing' (config) and 'Persona' (prompt).
        """
        log.info("Generating PR summary using model: %s", self.config['llm']['model'])
        
        try:
            response = self.client.chat.completions.create(
                model=self.config['llm']['model'],
                temperature=self.config['llm']['temperature'],
                max_tokens=self.config['llm']['max_tokens'],
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": f"Please summarize the following git delta:\n\n{git_diff}"}
                ]
            )
            if not response.choices or not response.choices[0].message.content:
                raise ValueError("Received empty response from OpenAI API.")
            else:
                log.info("Successfully generated PR summary.")
                return response.choices[0].message.content.strip()
        except Exception as e:
            log.error("Failed to generate AI summary: %s", e)
            raise