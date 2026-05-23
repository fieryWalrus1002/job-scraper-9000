#!/usr/bin/env python3
"""Throwaway CLI for hand-scoring the skills_fit seed gold.

Iterates through data/staging/skills_fit_seed_template.jsonl, pretty-prints each
posting, prompts for the _human_* fields, and appends scored records to
data/eval/skills_fit_ground_truth.jsonl.

If data/staging/skills_fit_seed_proposed.jsonl exists (from
propose_skills_fit_seed.py), the scorer runs in teacher-aware mode: it shows
the teacher's labels next to the posting and lets you accept the whole
proposal with a single keystroke, or override specific fields. The teacher's
labels are preserved in the output as _teacher_* fields for the audit trail.

Phase R only. Replace with the Streamlit reviewer in Phase G.

Usage:
    uv run scripts/score_skills_fit_seed.py
    uv run scripts/score_skills_fit_seed.py --in path/to/template.jsonl --out path/to/gold.jsonl

Controls per record (teacher-aware mode):
    score:       a=accept teacher's full proposal   1-5=override score
                 s=skip this candidate              q=save and quit
    other fields: press enter to keep teacher's value, or type to override
    notes:        always required (highest signal on flips)
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from pathlib import Path

DEFAULT_IN = Path("data/staging/skills_fit_seed_template.jsonl")
DEFAULT_PROPOSED = Path("data/staging/skills_fit_seed_proposed.jsonl")
DEFAULT_OUT = Path("data/eval/skills_fit_ground_truth.jsonl")

VALID_SCORES = {1, 2, 3, 4, 5}
CONFIDENCE_MAP = {"l": "low", "m": "medium", "h": "high"}
CONFIDENCE_SHORT = {"low": "l", "medium": "m", "high": "h"}

TEACHER_FIELDS = (
    "_teacher_fit_score",
    "_teacher_confidence",
    "_teacher_score_rationale",
    "_teacher_top_matches",
    "_teacher_gaps",
    "_teacher_hard_concerns",
    "_teacher_model",
    "_teacher_profile_version",
)


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


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")


def has_teacher_proposal(rec: dict) -> bool:
    return rec.get("_teacher_fit_score") in VALID_SCORES


def print_record(rec: dict, idx: int, total: int) -> None:
    print("\n" + "=" * 78)
    print(f"  [{idx}/{total}]  {rec.get('title', '<no title>')}")
    print(
        f"  {rec.get('company', '<no company>')}  ·  {rec.get('location', '<no location>')}"
    )
    print(f"  url: {rec.get('source_url', '<no url>')}")
    remote = rec.get("_remote_analysis") or {}
    if remote:
        print(
            f"  remote: {remote.get('remote_score')}  reasoning: {remote.get('reasoning', '')[:100]}"
        )
    print("=" * 78)
    desc = rec.get("description", "")
    for para in desc.split("\n"):
        if para.strip():
            print(textwrap.fill(para, width=78, replace_whitespace=False))
        else:
            print()
    print("=" * 78)


def print_teacher_proposal(rec: dict) -> None:
    print()
    print(f"  TEACHER ({rec.get('_teacher_model', '?')}) proposes:")
    print(
        f"    fit_score:      {rec.get('_teacher_fit_score')}  ({rec.get('_teacher_confidence')})"
    )
    rationale = rec.get("_teacher_score_rationale", "")
    if rationale:
        print(
            f"    rationale:      {textwrap.fill(rationale, width=72, subsequent_indent='                    ')}"
        )
    for label, key in (
        ("top_matches", "_teacher_top_matches"),
        ("gaps", "_teacher_gaps"),
        ("hard_concerns", "_teacher_hard_concerns"),
    ):
        items = rec.get(key) or []
        if items:
            print(f"    {label}:".ljust(20) + "; ".join(items))
    print()


def prompt_score(has_teacher: bool) -> int | str:
    if has_teacher:
        msg = "fit_score [a=accept teacher / 1-5 to override / s skip / q quit]: "
    else:
        msg = "fit_score [1-5, s=skip, q=quit]: "
    while True:
        raw = input(msg).strip().lower()
        if raw in {"s", "q"}:
            return raw
        if has_teacher and raw == "a":
            return "a"
        try:
            v = int(raw)
        except ValueError:
            print("  ! invalid input")
            continue
        if v in VALID_SCORES:
            return v
        print("  ! score must be 1-5")


def prompt_confidence(default: str | None = None) -> str:
    if default and default in CONFIDENCE_SHORT:
        msg = f"confidence [l/m/h, teacher: {default}, enter to keep]: "
    else:
        msg = "confidence [l/m/h]: "
    while True:
        raw = input(msg).strip().lower()
        if not raw and default in CONFIDENCE_SHORT:
            return default
        if raw in CONFIDENCE_MAP:
            return CONFIDENCE_MAP[raw]
        print("  ! enter l, m, or h")


def prompt_list(label: str, default: list[str] | None = None) -> list[str]:
    if default:
        preview = "; ".join(default)
        msg = f"{label} (teacher: {preview!r}, enter to keep, or new list): "
    else:
        msg = f"{label} (semicolon-separated, blank=none): "
    raw = input(msg).strip()
    if not raw:
        return list(default) if default else []
    return [s.strip() for s in raw.split(";") if s.strip()]


def prompt_notes() -> str:
    while True:
        raw = input(
            "notes (REQUIRED — why this band, what tipped it, esp. if flipping teacher): "
        ).strip()
        if raw:
            return raw
        print("  ! notes are mandatory — they become Phase G's calibration anchors")


def print_band_counts(counts: dict[int, int], target: int = 5) -> None:
    parts = []
    for band in (1, 2, 3, 4, 5):
        n = counts.get(band, 0)
        marker = "✓" if n >= target else " "
        parts.append(f"{band}:{n}/{target}{marker}")
    print("  bands: " + "  ".join(parts))


def merge_teacher_fields(rec: dict, proposed_by_id: dict[str, dict]) -> dict:
    """Attach _teacher_* fields to a template record from the proposed file (if present)."""
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
    p.add_argument(
        "--in",
        dest="input",
        default=str(DEFAULT_IN),
        help=f"Template JSONL (default: {DEFAULT_IN})",
    )
    p.add_argument(
        "--proposed",
        default=str(DEFAULT_PROPOSED),
        help=f"Teacher proposals JSONL — used when present (default: {DEFAULT_PROPOSED})",
    )
    p.add_argument(
        "--out",
        default=str(DEFAULT_OUT),
        help=f"Gold JSONL to append to (default: {DEFAULT_OUT})",
    )
    p.add_argument(
        "--target-per-band",
        type=int,
        default=5,
        help="Stratification target per band (default: 5)",
    )
    args = p.parse_args()

    in_path = Path(args.input)
    proposed_path = Path(args.proposed)
    out_path = Path(args.out)

    candidates = load_jsonl(in_path)
    if not candidates:
        print(f"No candidates in {in_path}", file=sys.stderr)
        sys.exit(1)

    proposed = load_jsonl(proposed_path)
    proposed_by_id = {r["source_job_id"]: r for r in proposed if r.get("source_job_id")}

    existing = load_jsonl(out_path)
    scored_ids = {r.get("dedup_hash") for r in existing if r.get("dedup_hash")}
    band_counts: dict[int, int] = {}
    for r in existing:
        s = r.get("_human_fit_score")
        if isinstance(s, int):
            band_counts[s] = band_counts.get(s, 0) + 1

    remaining = [
        merge_teacher_fields(c, proposed_by_id)
        for c in candidates
        if c.get("dedup_hash") not in scored_ids
    ]

    print(f"template:   {in_path}  ({len(candidates)} candidates)")
    print(f"proposed:   {proposed_path}  ({len(proposed_by_id)} with teacher labels)")
    print(f"gold file:  {out_path}  ({len(existing)} already scored)")
    print(f"to review:  {len(remaining)}")
    print_band_counts(band_counts, args.target_per_band)

    total = len(remaining)
    for idx, rec in enumerate(remaining, start=1):
        print_record(rec, idx, total)
        has_teacher = has_teacher_proposal(rec)
        if has_teacher:
            print_teacher_proposal(rec)
        print_band_counts(band_counts, args.target_per_band)

        score = prompt_score(has_teacher)
        if score == "q":
            print("\nQuitting. Progress saved.")
            break
        if score == "s":
            print("  → skipped")
            continue

        if score == "a":
            score = rec["_teacher_fit_score"]
            confidence = rec.get("_teacher_confidence", "medium")
            top_matches = list(rec.get("_teacher_top_matches") or [])
            gaps = list(rec.get("_teacher_gaps") or [])
            hard_concerns = list(rec.get("_teacher_hard_concerns") or [])
            print(f"  → accepted teacher proposal (band {score})")
        else:
            assert isinstance(score, int)
            teacher_conf = rec.get("_teacher_confidence") if has_teacher else None
            confidence = prompt_confidence(teacher_conf)
            top_matches = prompt_list(
                "top_matches", rec.get("_teacher_top_matches") if has_teacher else None
            )
            gaps = prompt_list(
                "gaps", rec.get("_teacher_gaps") if has_teacher else None
            )
            hard_concerns = prompt_list(
                "hard_concerns",
                rec.get("_teacher_hard_concerns") if has_teacher else None,
            )

        notes = prompt_notes()

        scored = {
            **rec,
            "_human_fit_score": score,
            "_human_confidence": confidence,
            "_human_top_matches": top_matches,
            "_human_gaps": gaps,
            "_human_hard_concerns": hard_concerns,
            "_human_notes": notes,
        }
        append_jsonl(out_path, scored)
        band_counts[score] = band_counts.get(score, 0) + 1
        print(f"  → saved (band {score})")

    print("\nFinal band counts:")
    print_band_counts(band_counts, args.target_per_band)
    print(f"Gold file: {out_path}")


if __name__ == "__main__":
    main()
