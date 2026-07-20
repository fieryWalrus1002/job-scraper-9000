import json
import os
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[2]))

from agents.remote_filter.models import SCHEMA_VERSION
from agents.remote_filter.utils import REMOTE_FILTER_PROMPT_PATH
from review_ui.remote_filter_review import (
    ACTIVE_LABELS,
    MissingAnalysisError,
    extract_remote_analysis,
    proposed_classification,
    suggested_verdict,
    validate_active_label,
)
from utils.git_info import get_git_metadata, get_prompt_hash

_PROMPT_FILE = REMOTE_FILTER_PROMPT_PATH

STAGING = "data/staging/to_review.jsonl"
EVAL = "data/eval/ground_truth.jsonl"

LABELS = list(ACTIVE_LABELS)

st.set_page_config(layout="wide", page_title="HITL Reviewer")

# ── Session state ─────────────────────────────────────────────────────────────

if "idx" not in st.session_state:
    st.session_state.idx = 0
if "git_meta" not in st.session_state:
    st.session_state.git_meta = get_git_metadata()
if "prompt_hash" not in st.session_state:
    st.session_state.prompt_hash = (
        get_prompt_hash(_PROMPT_FILE) if _PROMPT_FILE.exists() else "unknown"
    )
if "skipped_idx" not in st.session_state:
    st.session_state.skipped_idx = set()

git_meta = st.session_state.git_meta
prompt_hash = st.session_state.prompt_hash

# ── Data helpers ──────────────────────────────────────────────────────────────


def load_staging() -> list[dict]:
    if not os.path.exists(STAGING):
        return []
    with open(STAGING) as f:
        return [json.loads(line) for line in f if line.strip()]


def load_reviewed() -> dict[str, dict]:
    """Last-saved decision per dedup_hash from ground_truth (later entries win)."""
    if not os.path.exists(EVAL):
        return {}
    seen: dict[str, dict] = {}
    with open(EVAL) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            h = r.get("dedup_hash")
            if h:
                seen[h] = {
                    "verdict": r.get("_human_verdict"),
                    "policy": r.get("_human_policy"),
                    "corrected": r.get("_corrected", False),
                }
    return seen


if "reviewed" not in st.session_state:
    st.session_state.reviewed = load_reviewed()
    st.session_state._resuming = True  # flag to auto-advance on first render

# ── Build / save ──────────────────────────────────────────────────────────────


def build_metadata() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "prompt_hash": prompt_hash,
        "prompt_file": _PROMPT_FILE.name,
        "commit": git_meta["commit"],
        "dirty": git_meta["dirty"],
        "reviewed_at": git_meta["timestamp"],
    }


def save_record(
    job: dict, verdict: str, policy: str, corrected: bool, note: str = ""
) -> None:
    validate_active_label(policy)
    os.makedirs(os.path.dirname(EVAL), exist_ok=True)
    record = {
        **job,
        "_human_verdict": verdict,
        "_human_policy": policy,
        "_human_classification": policy,
        "_corrected": corrected,
        "_review_metadata": build_metadata(),
    }
    if note:
        record["_correction_note"] = note
    with open(EVAL, "a") as f:
        f.write(json.dumps(record) + "\n")
    h = job.get("dedup_hash")
    if h:
        st.session_state.reviewed[h] = {
            "verdict": verdict,
            "policy": policy,
            "corrected": corrected,
        }


# ── Visual helpers ────────────────────────────────────────────────────────────


def status_dot(i: int, job: dict, idx: int, reviewed: dict, skipped: set[int]) -> str:
    if i == idx:
        return "🔵"
    h = job.get("dedup_hash", "")
    if h in reviewed:
        return "🟣" if reviewed[h]["corrected"] else "🟢"
    if i in skipped:
        return "🟡"
    return "⬜"


def status_grid(
    jobs: list, idx: int, reviewed: dict, skipped: set[int], per_row: int = 20
) -> str:
    dots = [status_dot(i, j, idx, reviewed, skipped) for i, j in enumerate(jobs)]
    rows = ["".join(dots[i : i + per_row]) for i in range(0, len(dots), per_row)]
    return "<br/>".join(rows)


# ── Load staging ──────────────────────────────────────────────────────────────

jobs = load_staging()
total = len(jobs)

if total == 0:
    st.warning(
        f"No records found in `{STAGING}`. Run remote-filter, then "
        "`uv run scripts/sample_for_review.py` first."
    )
    st.stop()

# On first load after a restart, jump to the first unreviewed record.
if st.session_state.get("_resuming"):
    st.session_state._resuming = False
    for i, j in enumerate(jobs):
        if j.get("dedup_hash", "") not in st.session_state.reviewed:
            st.session_state.idx = i
            break

# ── Dirty warning ─────────────────────────────────────────────────────────────

if git_meta["dirty"]:
    st.warning(
        "Repo is dirty — uncommitted changes exist. "
        "Records saved now will be marked `dirty: true`.",
        icon="⚠️",
    )

# ── Navigation bar (always visible) ──────────────────────────────────────────

reviewed_count = sum(
    1 for j in jobs if j.get("dedup_hash", "") in st.session_state.reviewed
)
skipped_count = len(st.session_state.skipped_idx)
pending_count = total - reviewed_count - skipped_count

nav_l, nav_mid, nav_r = st.columns([1, 5, 1])

with nav_l:
    back_disabled = st.session_state.idx <= 0
    if st.button("← Back", use_container_width=True, disabled=back_disabled):
        st.session_state.idx -= 1
        st.rerun()

with nav_mid:
    display_idx = min(st.session_state.idx, total - 1)
    st.caption(
        f"Record **{display_idx + 1}** of {total}  ·  "
        f"🟢 {reviewed_count} reviewed  "
        f"🟣 confirmed+corrected  "
        f"🟡 {skipped_count} skipped  "
        f"⬜ {pending_count} pending"
    )
    st.markdown(
        '<div style="white-space: nowrap;">'
        + status_grid(
            jobs,
            display_idx,
            st.session_state.reviewed,
            st.session_state.skipped_idx,
            per_row=20,
        )
        + "</div>",
        unsafe_allow_html=True,
    )
    st.caption("🔵 current  🟢 confirmed  🟣 corrected  🟡 skipped  ⬜ pending")

with nav_r:
    fwd_disabled = st.session_state.idx >= total - 1
    if st.button("Forward →", use_container_width=True, disabled=fwd_disabled):
        st.session_state.idx += 1
        st.rerun()

# ── Completion screen ─────────────────────────────────────────────────────────

if st.session_state.idx >= total:
    st.success(
        f"Batch complete! {total} records processed — {reviewed_count} reviewed, {skipped_count} skipped."
    )
    if st.button("Start over"):
        st.session_state.idx = 0
        st.session_state.skipped_idx = set()
        st.rerun()
    st.stop()

# ── Current record ────────────────────────────────────────────────────────────

idx = st.session_state.idx
job = jobs[idx]
job_hash = job.get("dedup_hash", "")
prior = st.session_state.reviewed.get(job_hash)

if prior:
    icon = "✅" if prior["verdict"] == "pass" else "🗑️"
    badge = "corrected" if prior["corrected"] else "confirmed"
    st.info(
        f"{icon} Already submitted — verdict: **{prior['verdict']}** · "
        f"policy: **{prior['policy']}** · {badge}. "
        f"Saving again will append a correction (last entry wins in eval).",
        icon="✅",
    )

try:
    analysis = extract_remote_analysis(job)
except MissingAnalysisError as exc:
    analysis = {}
    analysis_error = str(exc)
else:
    analysis_error = ""

proposed_policy = proposed_classification(analysis)
proposed_verdict = suggested_verdict(proposed_policy)

col1, col2 = st.columns([2, 1])

with col1:
    st.subheader(f"{job.get('title', 'Untitled')} — {job.get('company', '')}")
    sp = job.get("search_params") or {}
    sp_parts = [
        f"{k}={v}" for k, v in sp.items() if k in ("keywords", "workplace", "job_type")
    ]
    search_ctx = f"  ·  search: {', '.join(sp_parts)}" if sp_parts else ""
    st.caption(f"{job.get('location', '')}  ·  {job.get('source', '')}{search_ctx}")
    st.divider()
    st.write(job.get("description", "_No description_"))

with col2:
    st.subheader("Classifier Proposal")
    if analysis:
        st.info(analysis.get("reasoning_trace", "_No reasoning trace_"))
        st.metric("Verdict", proposed_verdict)
        st.metric("Classification", proposed_policy or "unknown")
        if analysis.get("timezone_requirements"):
            st.caption("Timezone reqs: " + ", ".join(analysis["timezone_requirements"]))
        if analysis.get("key_phrases"):
            st.caption("Key phrases: " + " · ".join(analysis["key_phrases"]))
    else:
        st.error(f"Could not parse classifier proposal: {analysis_error}")

    st.divider()

    confirm_disabled = proposed_policy not in LABELS or proposed_verdict == "unknown"
    if st.button(
        "Confirm Proposal ✅",
        use_container_width=True,
        type="primary",
        disabled=confirm_disabled,
    ):
        assert proposed_policy is not None
        save_record(job, proposed_verdict, proposed_policy, corrected=False)
        st.session_state.idx += 1
        st.rerun()

    st.subheader("Correct Label")
    corrected_policy = st.selectbox(
        "Remote policy",
        LABELS,
        index=LABELS.index(proposed_policy) if proposed_policy in LABELS else 0,
    )
    corrected_verdict = st.radio(
        "Pass or trash?",
        ["pass", "trash"],
        horizontal=True,
        index=0 if proposed_verdict == "pass" else 1,
    )
    correction_note = st.text_input("Note (optional)")

    if st.button("Save Correction ❌", use_container_width=True):
        save_record(
            job,
            corrected_verdict,
            corrected_policy,
            corrected=True,
            note=correction_note,
        )
        st.session_state.idx += 1
        st.rerun()

    if st.button("Skip (no label) ⏭", use_container_width=True):
        st.session_state.skipped_idx.add(idx)
        st.session_state.idx += 1
        st.rerun()

    st.divider()
    st.caption(
        f"schema `{SCHEMA_VERSION}` · prompt `{prompt_hash}` · "
        f"`{git_meta['commit'][:12]}`{'  ⚠️ dirty' if git_meta['dirty'] else ''}"
    )
