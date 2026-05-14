import os
import pathlib
import yaml
import logging
from openai import OpenAI
from dotenv import load_dotenv

# Peer Review: Standardizing logging in the module
log = logging.getLogger(__name__)

class PRSummarizer:
    def __init__(self, config_path: str, prompt_path: str):
        # 1. Attempt to load .env for local dev. 
        # If it's missing (like in GitHub Actions), this simply does nothing.
        load_dotenv() 

        self.config = self._load_config(config_path)
        self.system_prompt = self._load_and_strip_prompt(prompt_path)
        
        # 2. Grab from environment. 
        # In GH Actions, this is populated by 'env:' in your workflow YAML.
        api_key = os.environ.get("OPENAI_API_KEY")
        
        if not api_key:
            # We raise a ValueError instead of sys.exit(1) inside a class.
            # This allows the calling script or a test suite to catch the error.
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