#!/usr/bin/env python3
"""Parse filled-in skills_fit review Markdown files into the gold JSONL.

For each .md file in the review directory, extracts the YAML block under
`## YOUR REVIEW`, validates the fields, and appends a scored record to
`data/eval/skills_fit_ground_truth.jsonl`.

Records are skipped (not written to gold) if:
  - `fit_score` is unset, "SKIP", or out of range (1-5)
  - `confidence` is not one of low/medium/high
  - `notes` is empty (notes are mandatory — they become Phase G's calibration anchors)
  - `dedup_hash` is already in the gold file (no duplicates)

Validation failures are reported per-file and the script continues.

Usage:
    uv run scripts/parse_skills_fit_review_md.py
    uv run scripts/parse_skills_fit_review_md.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

DEFAULT_IN = Path("data/staging/skills_fit_seed_template.jsonl")
DEFAULT_PROPOSED = Path("data/staging/skills_fit_seed_proposed.jsonl")
DEFAULT_REVIEW_DIR = Path("data/staging/skills_fit_review/")
DEFAULT_GOLD = Path("data/eval/skills_fit_ground_truth.jsonl")

VALID_SCORES = {1, 2, 3, 4, 5}
VALID_CONFIDENCE = {"low", "medium", "high"}

YAML_BLOCK_RE = re.compile(
    r"## YOUR REVIEW.*?```yaml\n(.*?)\n```",
    re.DOTALL,
)

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


_QUOTE_MAP = str.maketrans(
    {
        "“": '"',
        "”": '"',  # " "
        "‘": "'",
        "’": "'",  # ' '
    }
)


def _normalize_quotes(text: str) -> str:
    return text.translate(_QUOTE_MAP)


def extract_review_yaml(md_text: str) -> dict | None:
    m = YAML_BLOCK_RE.search(md_text)
    if not m:
        return None
    data = yaml.safe_load(_normalize_quotes(m.group(1)))
    if data is None:
        return None
    if not isinstance(data, dict):
        raise ValueError(
            f"YAML block is {type(data).__name__}, expected a mapping (dict)"
        )
    return data


def validate_review(data: dict) -> tuple[bool, str | None]:
    """Returns (is_valid, reason_for_skip_or_None)."""
    fit_score = data.get("fit_score")
    if fit_score == "SKIP":
        return False, "fit_score set to SKIP"
    if not isinstance(fit_score, int) or fit_score not in VALID_SCORES:
        return False, f"fit_score is {fit_score!r}, must be 1-5"

    confidence = data.get("confidence")
    if confidence not in VALID_CONFIDENCE:
        return False, f"confidence is {confidence!r}, must be one of low/medium/high"

    notes = data.get("notes")
    if not isinstance(notes, str) or not notes.strip():
        return False, "notes is empty — required as the calibration anchor"

    return True, None


def print_band_counts(records: list[dict], target: int = 5) -> None:
    counts: dict[int, int] = {}
    for r in records:
        s = r.get("_human_fit_score")
        if isinstance(s, int):
            counts[s] = counts.get(s, 0) + 1
    print("Gold band counts (target {0}/band):".format(target))
    for band in (1, 2, 3, 4, 5):
        n = counts.get(band, 0)
        marker = " ✓" if n >= target else ""
        print(f"  {band}: {n}/{target}{marker}")


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--review-dir", default=str(DEFAULT_REVIEW_DIR))
    p.add_argument("--in", dest="input", default=str(DEFAULT_IN))
    p.add_argument("--proposed", default=str(DEFAULT_PROPOSED))
    p.add_argument("--gold", default=str(DEFAULT_GOLD))
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and validate but don't write to gold",
    )
    args = p.parse_args()

    review_dir = Path(args.review_dir)
    in_path = Path(args.input)
    proposed_path = Path(args.proposed)
    gold_path = Path(args.gold)

    if not review_dir.exists():
        print(f"Review dir not found: {review_dir}", file=sys.stderr)
        sys.exit(1)

    candidates = load_jsonl(in_path)
    candidates_by_id = {
        c["source_job_id"]: c for c in candidates if c.get("source_job_id")
    }

    proposed = load_jsonl(proposed_path)
    proposed_by_id = {r["source_job_id"]: r for r in proposed if r.get("source_job_id")}

    gold = load_jsonl(gold_path)
    scored_ids = {r.get("dedup_hash") for r in gold if r.get("dedup_hash")}

    md_files = sorted(review_dir.glob("*.md"))
    if not md_files:
        print(f"No .md files in {review_dir}", file=sys.stderr)
        sys.exit(1)

    parsed = 0
    skipped_invalid = 0
    skipped_already_in_gold = 0
    errors: list[tuple[str, str]] = []

    for md_path in md_files:
        try:
            text = md_path.read_text()
            data = extract_review_yaml(text)
        except yaml.YAMLError as e:
            errors.append((md_path.name, f"YAML parse error: {e}"))
            continue
        except ValueError as e:
            errors.append((md_path.name, f"YAML structure error: {e}"))
            continue
        except Exception as e:
            errors.append((md_path.name, f"unexpected: {type(e).__name__}: {e}"))
            continue

        if data is None:
            errors.append((md_path.name, "no YAML block found under '## YOUR REVIEW'"))
            continue

        source_job_id = data.get("source_job_id")
        if not source_job_id:
            errors.append((md_path.name, "source_job_id missing in identifiers"))
            continue

        original = candidates_by_id.get(source_job_id)
        if original is None:
            errors.append(
                (md_path.name, f"source_job_id {source_job_id!r} not in template")
            )
            continue

        record_dedup_hash = original.get("dedup_hash")
        if record_dedup_hash and record_dedup_hash in scored_ids:
            skipped_already_in_gold += 1
            continue

        is_valid, reason = validate_review(data)
        if not is_valid:
            skipped_invalid += 1
            print(f"  skip  {md_path.name}: {reason}")
            continue

        teacher = proposed_by_id.get(source_job_id, {})
        teacher_fields = {k: teacher[k] for k in TEACHER_FIELDS if k in teacher}

        scored = {
            **original,
            **teacher_fields,
            "_human_fit_score": data["fit_score"],
            "_human_confidence": data["confidence"],
            "_human_top_matches": list(data.get("top_matches") or []),
            "_human_gaps": list(data.get("gaps") or []),
            "_human_hard_concerns": list(data.get("hard_concerns") or []),
            "_human_notes": data["notes"].strip(),
        }
        correction_note = data.get("correction_note")
        if isinstance(correction_note, str) and correction_note.strip():
            scored["_human_correction_note"] = correction_note.strip()

        if args.dry_run:
            print(
                f"  ok    {md_path.name}: "
                f"fit_score={data['fit_score']} ({data['confidence']})"
            )
        else:
            append_jsonl(gold_path, scored)
            if record_dedup_hash:
                scored_ids.add(record_dedup_hash)
            print(
                f"  saved {md_path.name}: "
                f"fit_score={data['fit_score']} ({data['confidence']})"
            )

        parsed += 1

    print()
    print(f"review dir:           {review_dir}")
    print(f"files found:          {len(md_files)}")
    print(f"parsed:               {parsed}")
    print(f"skipped (invalid):    {skipped_invalid}")
    print(f"skipped (in gold):    {skipped_already_in_gold}")
    print(f"errors:               {len(errors)}")

    if errors:
        print()
        print("ERRORS:")
        for name, msg in errors:
            print(f"  ! {name}: {msg}")

    if args.dry_run:
        print()
        print("(dry-run — nothing written to gold)")
    else:
        print()
        print_band_counts(load_jsonl(gold_path))


if __name__ == "__main__":
    main()
