import json
import os
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[2]))

from agents.remote_filter.models import SCHEMA_VERSION
from utils.git_info import get_git_metadata, get_prompt_hash

_PROMPT_FILE = Path(__file__).parents[2] / "prompts" / "remote_agent" / "system_prompt_v1.txt"

STAGING = "data/staging/to_review.jsonl"
EVAL = "data/eval/ground_truth.jsonl"

LABELS = ["fully_remote", "hybrid", "onsite", "onsite_disguised", "unclear"]

st.set_page_config(layout="wide", page_title="HITL Reviewer")

if "idx" not in st.session_state:
    st.session_state.idx = 0

if "git_meta" not in st.session_state:
    st.session_state.git_meta = get_git_metadata()

if "prompt_hash" not in st.session_state:
    st.session_state.prompt_hash = get_prompt_hash(_PROMPT_FILE) if _PROMPT_FILE.exists() else "unknown"

git_meta = st.session_state.git_meta
prompt_hash = st.session_state.prompt_hash

if git_meta["dirty"]:
    st.warning(
        f"Repo is dirty — uncommitted changes exist. The commit hash "
        f"`{git_meta['commit'][:12]}` does not fully describe the current "
        f"code state. Records saved now will be marked `dirty: true`.",
        icon="⚠️",
    )


def load_data():
    if not os.path.exists(STAGING):
        return []
    with open(STAGING) as f:
        return [json.loads(line) for line in f if line.strip()]


def build_metadata() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "prompt_hash": prompt_hash,
        "prompt_file": _PROMPT_FILE.name,
        "commit": git_meta["commit"],
        "dirty": git_meta["dirty"],
        "reviewed_at": git_meta["timestamp"],
    }


jobs = load_data()
total = len(jobs)

if total == 0:
    st.warning(f"No records found in `{STAGING}`. Run `merge_batch_results.py` first.")
    st.stop()

if st.session_state.idx >= total:
    st.success(f"Batch complete! {total} records reviewed.")
    if st.button("Start over"):
        st.session_state.idx = 0
        st.rerun()
    st.stop()

job = jobs[st.session_state.idx]
st.progress((st.session_state.idx) / total, text=f"Record {st.session_state.idx + 1} of {total}")

raw_content = (
    job.get("response", {})
    .get("body", {})
    .get("choices", [{}])[0]
    .get("message", {})
    .get("content", "{}")
)
try:
    analysis = json.loads(raw_content)
except (json.JSONDecodeError, TypeError):
    analysis = {}

teacher_verdict = "pass" if analysis.get("remote_classification") == "fully_remote" else "trash" if analysis.get("remote_classification") else "unknown"
teacher_policy = analysis.get("remote_classification", "unknown")

col1, col2 = st.columns([2, 1])

with col1:
    st.subheader(f"{job.get('title', 'Untitled')} — {job.get('company', '')}")
    st.caption(f"{job.get('location', '')}  ·  {job.get('source', '')}")
    st.divider()
    st.write(job.get("description", "_No description_"))

with col2:
    st.subheader("Teacher Reasoning")
    if analysis:
        st.info(analysis.get("reasoning_trace", "_No reasoning trace_"))
        st.metric("Verdict", teacher_verdict)
        st.metric("Policy", teacher_policy)
        if analysis.get("timezone_requirements"):
            st.caption("Timezone reqs: " + ", ".join(analysis["timezone_requirements"]))
        if analysis.get("key_phrases"):
            st.caption("Key phrases: " + " · ".join(analysis["key_phrases"]))
    else:
        st.error("Could not parse teacher response.")

    st.divider()

    if st.button("Confirm Teacher ✅", use_container_width=True, type="primary"):
        os.makedirs(os.path.dirname(EVAL), exist_ok=True)
        with open(EVAL, "a") as f:
            record = {
                **job,
                "_human_verdict": teacher_verdict,
                "_human_policy": teacher_policy,
                "_corrected": False,
                "_review_metadata": build_metadata(),
            }
            f.write(json.dumps(record) + "\n")
        st.session_state.idx += 1
        st.rerun()

    st.subheader("Correct Label")
    corrected_policy = st.selectbox("Remote policy", LABELS, index=LABELS.index(teacher_policy) if teacher_policy in LABELS else 0)
    corrected_verdict = st.radio("Pass or trash?", ["pass", "trash"], horizontal=True, index=0 if teacher_verdict == "pass" else 1)
    correction_note = st.text_input("Note (optional)")

    if st.button("Save Correction ❌", use_container_width=True):
        os.makedirs(os.path.dirname(EVAL), exist_ok=True)
        with open(EVAL, "a") as f:
            record = {
                **job,
                "_human_verdict": corrected_verdict,
                "_human_policy": corrected_policy,
                "_corrected": True,
                "_correction_note": correction_note,
                "_review_metadata": build_metadata(),
            }
            f.write(json.dumps(record) + "\n")
        st.session_state.idx += 1
        st.rerun()

    if st.button("Skip (no label) ⏭", use_container_width=True):
        st.session_state.idx += 1
        st.rerun()

    st.divider()
    st.caption(f"schema `{SCHEMA_VERSION}` · prompt `{prompt_hash}` · `{git_meta['commit'][:12]}`{'  ⚠️ dirty' if git_meta['dirty'] else ''}")
