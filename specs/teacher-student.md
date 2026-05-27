# Design Doc: Distillation for the remote_filter agent using a smarter model

## 1. Executive Summary

By utilizing a **Teacher-Student distillation pattern**, the system achieves the high-reasoning accuracy of flagship cloud models (GPT-5/4o) while executing final classification using high-speed, cost-effective local LLMs (Qwen3.6/Llama).

## 2. High-Level Architecture

The system is built as a Python-based monorepo utilizing a modular service architecture.

### 2.1 Component Overview

- **Ingestion (Scraper):** Python/JobSpy-based engine that aggregates raw listings into `data/raw/`.
- **Teacher Agent (Cloud Pass):** High-parameter model (GPT-5) that performs deep reasoning to categorize work policies.
- **Review UI (Streamlit):** A Human-in-the-Loop (HITL) interface for validating Teacher reasoning and creating a "Golden Dataset."
- **Student Agent (Local Pass):** A smaller, quantized model (7B-8B) running on an RTX 4090 that mimics the Teacher’s logic for production inference.

______________________________________________________________________

## 3. The Data Lifecycle (Medallion Pattern)

To ensure data integrity, we follow a strict directory-based state progression:

| Stage                | Path            | Purpose                                           |
| -------------------- | --------------- | ------------------------------------------------- |
| **Bronze (Raw)**     | `data/raw/`     | Initial scraped JSONL; untouched by models.       |
| **Silver (Staging)** | `data/staging/` | Teacher-annotated data awaiting human validation. |
| **Gold (Eval)**      | `data/eval/`    | Human-verified "Golden Dataset" (Ground Truth).   |

______________________________________________________________________

## 4. Methodology: Knowledge Distillation

Rather than relying on expensive cloud APIs for every job, we use the cloud as a **Supervisor**.

1. **Reasoning Extraction:** The Teacher is prompted to provide a `reasoning_trace`. This captures the *logic* (the "why") behind a classification.
1. **HITL Verification:** Humans verify the reasoning in the Review UI, correcting edge cases (e.g., "Remote in title, but Hybrid in fine print").
1. **Behavioral Cloning:** The `reasoning_trace` from the Gold dataset is used to "few-shot" or fine-tune the local Student model, effectively "cloning" GPT-5 level logic into a 7B local environment.

See the active teacher prompt at [`prompts/remote_agent_teacher/system_prompt.txt`](../prompts/remote_agent_teacher/system_prompt.txt). Historical copies live under `prompts/remote_agent_teacher/versions/`.

______________________________________________________________________

## 5. Technical Stack

- **Environment:** Ubuntu Workstation / Python 3.13 / `uv` for package management.
- **Models:** GPT-5 (Teacher) / Qwen 3.6, Llama 3.1 (Student).
- **Storage:** Local JSONL (Append-only) for simplicity and auditability.
- **UI:** Streamlit for rapid internal tooling development.

## 6. Roadmap

- **Phase 1:** (Complete) Multi-source scraping & v1 classification prompt.
- **Phase 2:** (Current) Batch API Teacher integration & Streamlit HITL Review.
- **Phase 3:** Local model distillation and baseline accuracy evaluation.
- **Phase 4:** Automated alerting (Slack/Discord) for "Pass" jobs.
