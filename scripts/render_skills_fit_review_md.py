#!/usr/bin/env python3
"""Render skills_fit seed candidates as one Markdown file per record for async review.

For each unreviewed candidate, writes a Markdown document containing:
  - The job posting (title, company, location, URL, full description)
  - The teacher's proposal (if present) — fit_score, rationale, lists
  - A YAML block at the bottom pre-populated with the teacher's values, for the
    human to ratify or override

Records already in the gold JSONL (by source_job_id) are skipped — the workflow
is idempotent. Pre-existing .md files are kept by default; pass --overwrite to
regenerate everything from scratch (destroys any in-progress edits).

The companion parser `parse_skills_fit_review_md.py` reads filled-in files and
appends scored records to data/eval/skills_fit_ground_truth.jsonl.

Usage:
    uv run scripts/render_skills_fit_review_md.py
    uv run scripts/render_skills_fit_review_md.py --out-dir data/staging/skills_fit_review/
    uv run scripts/render_skills_fit_review_md.py --overwrite
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import textwrap
from pathlib import Path

DEFAULT_IN = Path("data/staging/skills_fit_seed_template.jsonl")
DEFAULT_PROPOSED = Path("data/staging/skills_fit_seed_proposed.jsonl")
DEFAULT_GOLD = Path("data/eval/skills_fit_ground_truth.jsonl")
DEFAULT_OUT_DIR = Path("data/staging/skills_fit_review/")

VALID_SCORES = {1, 2, 3, 4, 5}

TEACHER_FIELDS = (
    "_teacher_fit_score",
    "_teacher_confidence",
    "_teacher_score_rationale",
    "_teacher_top_matches",
    "_teacher_gaps",
    "_teacher_hard_concerns",
    "_teacher_model",
    "_teacher_profile_version",
    "_teacher_prompt_file",
)

SLUG_RE = re.compile(r"[^a-z0-9]+")
SID_RE = re.compile(r"[^A-Za-z0-9_-]+")


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def slugify(s: str, max_len: int = 50) -> str:
    s = (s or "").lower()
    s = SLUG_RE.sub("-", s).strip("-")
    return s[:max_len] or "untitled"


def sid_safe(sid: str, max_len: int = 16) -> str:
    return SID_RE.sub("-", sid or "")[:max_len] or "noid"


def yaml_list(items: list[str]) -> str:
    """Render a list as YAML, json-quoting items so colons/special chars stay safe."""
    if not items:
        return " []"
    lines = [""] + [f"  - {json.dumps(item)}" for item in items]
    return "\n".join(lines)


def md_list(items: list[str]) -> str:
    if not items:
        return "  _(none)_"
    return "\n".join(f"  - {item}" for item in items)


def render_record(rec: dict, idx: int, total: int) -> str:
    title = rec.get("title", "<no title>")
    company = rec.get("company", "<no company>")
    location = rec.get("location") or "?"
    url = rec.get("source_url") or "?"
    source_job_id = rec.get("source_job_id", "") or ""
    dedup_hash = rec.get("dedup_hash", "") or ""
    description = rec.get("description", "") or ""

    teacher_present = rec.get("_teacher_fit_score") in VALID_SCORES
    teacher_model = rec.get("_teacher_model", "?")
    teacher_profile_version = rec.get("_teacher_profile_version", "?")

    paragraphs = [p for p in description.split("\n") if p.strip()]
    desc_wrapped = "\n\n".join(
        textwrap.fill(p, width=88, replace_whitespace=False) for p in paragraphs
    )

    if teacher_present:
        rationale = rec.get("_teacher_score_rationale", "") or ""
        rationale_wrapped = textwrap.fill(
            rationale,
            width=86,
            initial_indent="  > ",
            subsequent_indent="  > ",
        )
        top_matches = rec.get("_teacher_top_matches") or []
        gaps = rec.get("_teacher_gaps") or []
        hard_concerns = rec.get("_teacher_hard_concerns") or []

        teacher_section = (
            f"## Teacher proposal — `{teacher_model}` "
            f"(profile: `{teacher_profile_version}`)\n\n"
            f"- **fit_score:** {rec['_teacher_fit_score']} "
            f"(confidence: {rec.get('_teacher_confidence', '?')})\n"
            f"- **rationale:**\n\n"
            f"{rationale_wrapped}\n\n"
            f"- **top_matches:**\n{md_list(top_matches)}\n"
            f"- **gaps:**\n{md_list(gaps)}\n"
            f"- **hard_concerns:**\n{md_list(hard_concerns)}\n"
        )

        # Pre-populate the YAML with teacher values so accepting = save unchanged.
        yaml_fit_score = rec["_teacher_fit_score"]
        yaml_confidence = json.dumps(rec.get("_teacher_confidence") or "high")
        yaml_top_matches = yaml_list(top_matches)
        yaml_gaps = yaml_list(gaps)
        yaml_hard_concerns = yaml_list(hard_concerns)
    else:
        teacher_section = "## Teacher proposal\n\n_No teacher proposal for this record._\n"
        yaml_fit_score = '""'
        yaml_confidence = '""'
        yaml_top_matches = " []"
        yaml_gaps = " []"
        yaml_hard_concerns = " []"

    yaml_block = (
        "# === Identifiers (do not edit) ===\n"
        f"source_job_id: {json.dumps(source_job_id)}\n"
        f"dedup_hash: {json.dumps(dedup_hash)}\n"
        "\n"
        "# === Your review (edit below) ===\n"
        "# - fit_score: 1-5, or SKIP to drop this record from gold\n"
        "# - notes: REQUIRED — empty notes will not be parsed into gold\n"
        "# - lists can stay as-is to ratify the teacher's values, or be edited\n"
        "\n"
        f"fit_score: {yaml_fit_score}\n"
        f"confidence: {yaml_confidence}\n"
        f"top_matches:{yaml_top_matches}\n"
        f"gaps:{yaml_gaps}\n"
        f"hard_concerns:{yaml_hard_concerns}\n"
        'notes: ""\n'
        'correction_note: ""\n'
    )

    return (
        f"# [{idx:02d}/{total}] {title} @ {company}\n\n"
        f"**source_job_id:** `{source_job_id}`  \n"
        f"**dedup_hash:** `{dedup_hash}`  \n"
        f"**location:** {location}  \n"
        f"**url:** {url}\n\n"
        "---\n\n"
        "## Job posting\n\n"
        f"{desc_wrapped}\n\n"
        "---\n\n"
        f"{teacher_section}\n"
        "---\n\n"
        "## YOUR REVIEW\n\n"
        "Fill in the YAML block below. Save the file when done.\n\n"
        "```yaml\n"
        f"{yaml_block}"
        "```\n"
    )


def merge_teacher_fields(rec: dict, proposed_by_id: dict[str, dict]) -> dict:
    sid = rec.get("source_job_id")
    if sid and sid in proposed_by_id:
        p = proposed_by_id[sid]
        return {**rec, **{k: p[k] for k in TEACHER_FIELDS if k in p}}
    return rec


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--in", dest="input", default=str(DEFAULT_IN))
    p.add_argument("--proposed", default=str(DEFAULT_PROPOSED))
    p.add_argument("--gold", default=str(DEFAULT_GOLD))
    p.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    p.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing .md files (destroys in-progress edits)",
    )
    args = p.parse_args()

    in_path = Path(args.input)
    proposed_path = Path(args.proposed)
    gold_path = Path(args.gold)
    out_dir = Path(args.out_dir)

    candidates = load_jsonl(in_path)
    if not candidates:
        print(f"No candidates in {in_path}", file=sys.stderr)
        sys.exit(1)

    proposed = load_jsonl(proposed_path)
    proposed_by_id = {r["source_job_id"]: r for r in proposed if r.get("source_job_id")}

    gold = load_jsonl(gold_path)
    scored_ids = {r.get("source_job_id") for r in gold if r.get("source_job_id")}

    remaining = [
        merge_teacher_fields(c, proposed_by_id)
        for c in candidates
        if c.get("source_job_id") not in scored_ids
    ]

    out_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    skipped_existing = 0
    total = len(remaining)
    for idx, rec in enumerate(remaining, start=1):
        sid = sid_safe(rec.get("source_job_id", ""))
        slug = slugify(f"{rec.get('title', '')}-{rec.get('company', '')}")
        filename = f"{idx:02d}_{sid}_{slug}.md"
        path = out_dir / filename

        if path.exists() and not args.overwrite:
            skipped_existing += 1
            continue

        path.write_text(render_record(rec, idx, total))
        written += 1

    print(f"template:        {in_path}  ({len(candidates)} candidates)")
    print(f"proposed:        {proposed_path}  ({len(proposed_by_id)} with teacher labels)")
    print(f"gold:            {gold_path}  ({len(gold)} already scored, skipped)")
    print(f"out dir:         {out_dir}")
    print(f"files written:   {written}")
    if skipped_existing:
        print(
            f"files skipped:   {skipped_existing} already exist "
            "(use --overwrite to replace)"
        )
    print()
    print(f"Open the files in {out_dir} to fill in your reviews.")
    print("When done (or partway through), run:")
    print("  uv run scripts/parse_skills_fit_review_md.py")


if __name__ == "__main__":
    main()
