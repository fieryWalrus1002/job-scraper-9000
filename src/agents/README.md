# agents

The processing pipeline for job-scraper-9000. Reads raw JSONL from `data/raw/`, runs it through LLM agents, and produces filtered/scored output.

## Entry point

Agents are currently invoked via scripts rather than a unified CLI:

```bash
python scripts/run_remote_filter.py   # remote filter
```

## Agents

| Agent | Purpose |
| --- | --- |
| `remote-filter` | Classifies job postings by remote work policy using a structured-output LLM |

Future agents: `scorer`, `dispatcher`

## Provider configuration

Agents use OpenAI by default. Switch providers with env vars in `.env`:

| Variable | Default | Notes |
| --- | --- | --- |
| `LLM_PROVIDER` | `openai` | `openai` or `ollama` |
| `LLM_MODEL` | `gpt-4o-mini` / `qwen2.5:14b` | Override the model for the active provider |
| `OPENAI_API_KEY` | — | Required when `LLM_PROVIDER=openai` |
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` | Override when Ollama is not on localhost |

## Data flow

```
data/raw/*.jsonl
      ↓
  remote-filter run
      ↓
data/filtered/remote_filter_pass.jsonl   ← genuinely remote
data/trash/remote_filter_trash.jsonl     ← hybrid / onsite / dealbreakers
      ↓
  scorer run  (coming soon)
      ↓
data/scored/
      ↓
  dispatcher run  (coming soon)
      ↓
Discord / Slack hotlist
```
