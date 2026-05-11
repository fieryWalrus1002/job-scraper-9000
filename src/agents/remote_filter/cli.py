import argparse
import json
import logging
import sys
import uuid
from pathlib import Path

log = logging.getLogger(__name__)

DATA_RAW = Path("data/raw")
DATA_EVAL = Path("data/eval")
DATA_FILTERED = Path("data/filtered")
DATA_TRASH = Path("data/trash")

_CLASSIFICATIONS = [
    "fully_remote",
    "remote_with_quarterly_travel",
    "remote_with_monthly_travel",
    "remote_with_frequent_travel",
    "hybrid",
    "onsite_disguised",
    "location_restricted",
    "unclear",
]


# ---------------------------------------------------------------------------
# label
# ---------------------------------------------------------------------------

def _load_raw_jobs(raw_dir: Path) -> list[dict]:
    paths = [raw_dir] if raw_dir.is_file() else sorted(raw_dir.glob("*.jsonl"))
    jobs = []
    for path in paths:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    jobs.append(json.loads(line))
    return jobs


def _load_eval_records(eval_path: Path) -> set[str]:
    """Return set of already-labeled job IDs."""
    if not eval_path.exists():
        return set()
    seen = set()
    with open(eval_path) as f:
        for line in f:
            line = line.strip()
            if line:
                rec = json.loads(line)
                seen.add(rec.get("sample_id", ""))
    return seen


def _prompt(question: str, options: list[str] | None = None) -> str:
    if options:
        for i, opt in enumerate(options, 1):
            print(f"  {i}. {opt}")
    while True:
        val = input(f"{question}: ").strip()
        if val:
            return val


def _cmd_label(args) -> None:
    eval_path = DATA_EVAL / "remote_filter_eval.jsonl"
    DATA_EVAL.mkdir(parents=True, exist_ok=True)

    jobs = _load_raw_jobs(DATA_RAW)
    if not jobs:
        log.error("No jobs found in %s", DATA_RAW)
        sys.exit(1)

    labeled = _load_eval_records(eval_path)
    unlabeled = [j for j in jobs if j.get("id", j.get("job_id", "")) not in labeled]

    log.info("%d total jobs, %d already labeled, %d to label", len(jobs), len(labeled), len(unlabeled))

    if not unlabeled:
        print("All jobs are already labeled.")
        return

    with open(eval_path, "a") as out:
        for i, job in enumerate(unlabeled):
            title = job.get("title", "(no title)")
            company = job.get("company", "(no company)")
            url = job.get("job_url", job.get("url", ""))
            description = job.get("description", "")
            job_id = job.get("id", job.get("job_id", str(uuid.uuid4())))

            print(f"\n{'=' * 70}")
            print(f"[{i + 1}/{len(unlabeled)}]  {title} @ {company}")
            if url:
                print(f"URL: {url}")
            print(f"{'-' * 70}")
            # Show first 1500 chars — enough to classify without scrolling forever
            print(description[:1500])
            if len(description) > 1500:
                print(f"... [{len(description) - 1500} chars truncated]")
            print(f"{'=' * 70}")

            print("\nClassification:")
            for idx, cls in enumerate(_CLASSIFICATIONS, 1):
                print(f"  {idx}. {cls}")
            print("  s. skip this posting")

            classification: str | None = None
            while True:
                choice = input("Choice: ").strip().lower()
                if choice == "s":
                    break
                if choice.isdigit() and 1 <= int(choice) <= len(_CLASSIFICATIONS):
                    classification = _CLASSIFICATIONS[int(choice) - 1]
                    break
                print("  Enter a number 1-8 or 's' to skip.")

            if choice == "s":
                continue
            if classification is None:
                log.warning("Skipping %s @ %s — no classification selected", title, company)
                continue

            while True:
                pass_choice = input("Should this pass the filter? (y/n): ").strip().lower()
                if pass_choice in ("y", "n"):
                    should_pass = pass_choice == "y"
                    break

            travel_input = input("Travel days range (e.g. '0-4', '12-24', or blank): ").strip()
            if travel_input and "-" in travel_input:
                parts = travel_input.split("-")
                try:
                    travel_range = (int(parts[0]), int(parts[1]))
                except ValueError:
                    travel_range = None
            else:
                travel_range = None

            notes = input("Notes (optional): ").strip()

            record = {
                "sample_id": job_id,
                "title": title,
                "company": company,
                "description": description,
                "expected_classification": classification,
                "expected_should_pass_filter": should_pass,
                "expected_travel_days_range": list(travel_range) if travel_range else None,
                "notes": notes,
            }
            out.write(json.dumps(record) + "\n")
            out.flush()
            log.info("Saved label for %s @ %s", title, company)

    print(f"\nDone. Eval records saved to {eval_path}")


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

def _cmd_run(args) -> None:
    from dotenv import load_dotenv
    load_dotenv()

    from agents.remote_filter.utils import analyze_remote, passes_remote_filter
    from agents.remote_filter.models import UserPreferences

    DATA_FILTERED.mkdir(parents=True, exist_ok=True)
    DATA_TRASH.mkdir(parents=True, exist_ok=True)

    prefs = UserPreferences(
        max_travel=args.max_travel,
        unclear_routing=args.unclear_routing,
        user_location=args.location,
    )

    raw_dir = Path(args.input)
    jobs = _load_raw_jobs(raw_dir)
    if not jobs:
        log.error("No jobs found in %s", raw_dir)
        sys.exit(1)

    log.info("Running remote-filter agent on %d jobs...", len(jobs))

    passed = failed = skipped = 0
    pass_path = DATA_FILTERED / "remote_filter_pass.jsonl"
    trash_path = DATA_TRASH / "remote_filter_trash.jsonl"

    with open(pass_path, "w") as pass_f, open(trash_path, "w") as trash_f:
        for job in jobs:
            description = job.get("description", "")
            title = job.get("title", "")
            company = job.get("company", "")

            if not description:
                log.warning("Skipping %s @ %s — no description", title, company)
                skipped += 1
                continue

            analysis = analyze_remote(description)
            if analysis is None:
                log.warning("Agent failed on %s @ %s — skipping", title, company)
                skipped += 1
                continue

            ok, reason = passes_remote_filter(analysis, prefs)
            enriched = {
                **job,
                "_remote_analysis": analysis.model_dump(),
                "_filter_result": "pass" if ok else "trash",
                "_filter_reason": reason,
            }

            if ok:
                pass_f.write(json.dumps(enriched) + "\n")
                passed += 1
                log.info("PASS  %s @ %s (%s)", title, company, analysis.remote_classification)
            else:
                trash_f.write(json.dumps(enriched) + "\n")
                failed += 1
                log.info("TRASH %s @ %s — %s", title, company, reason)

    log.info("Done — %d pass | %d trash | %d skipped", passed, failed, skipped)
    log.info("Pass  → %s", pass_path)
    log.info("Trash → %s", trash_path)


# ---------------------------------------------------------------------------
# review
# ---------------------------------------------------------------------------

_ANSI = {
    "reset":  "\033[0m",
    "bold":   "\033[1m",
    "green":  "\033[92m",
    "red":    "\033[91m",
    "yellow": "\033[93m",
    "cyan":   "\033[96m",
    "dim":    "\033[2m",
}

def _c(text: str, *codes: str) -> str:
    prefix = "".join(_ANSI[c] for c in codes)
    return f"{prefix}{text}{_ANSI['reset']}"


def _print_job(job: dict, index: int, total: int) -> None:
    analysis = job.get("_remote_analysis", {})
    result = job.get("_filter_result", "?")
    reason = job.get("_filter_reason", "?")
    url = job.get("job_url", job.get("url", ""))

    result_color = "green" if result == "pass" else "red"
    result_label = _c(f"  {result.upper()}  ", result_color, "bold")

    print(f"\n{'━' * 70}")
    print(f"{_c(f'[{index}/{total}]', 'dim')}  {_c(job.get('title', ''), 'bold')}  {_c('@ ' + job.get('company', ''), 'cyan')}")
    if url:
        print(_c(url, "dim"))
    print(f"{'━' * 70}")

    cls = analysis.get("remote_classification", "?")
    conf = analysis.get("confidence", "?")
    print(f"Classification : {_c(cls, 'yellow')}  (confidence: {conf})")
    print(f"Filter result  : {result_label}  reason: {reason}")

    if analysis.get("travel_description"):
        print(f"Travel         : {analysis['travel_description']}")
    if analysis.get("estimated_travel_days_per_year") is not None:
        print(f"Travel days/yr : {analysis['estimated_travel_days_per_year']}")
    if analysis.get("location_restrictions"):
        print(f"Location       : {', '.join(analysis['location_restrictions'])}")
    if analysis.get("requires_relocation"):
        print(_c("⚠  requires_relocation", "red"))
    if analysis.get("requires_local_presence"):
        print(_c("⚠  requires_local_presence", "red"))

    print(f"\n{_c('Reasoning:', 'bold')}")
    print(f"  {analysis.get('reasoning', '(none)')}")


def _cmd_review(args) -> None:
    bucket = args.bucket

    if bucket == "trash":
        paths = [DATA_TRASH / "remote_filter_trash.jsonl"]
    elif bucket == "pass":
        paths = [DATA_FILTERED / "remote_filter_pass.jsonl"]
    else:
        paths = [
            DATA_TRASH / "remote_filter_trash.jsonl",
            DATA_FILTERED / "remote_filter_pass.jsonl",
        ]

    jobs = []
    for p in paths:
        if p.exists():
            with open(p) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        jobs.append(json.loads(line))

    if not jobs:
        log.error("No jobs found to review in %s", [str(p) for p in paths])
        sys.exit(1)

    eval_path = DATA_EVAL / "remote_filter_eval.jsonl"
    DATA_EVAL.mkdir(parents=True, exist_ok=True)
    labeled = _load_eval_records(eval_path)

    print(_c(f"\nReviewing {len(jobs)} jobs from bucket: {bucket}", "bold"))
    print("Keys:  [k] keep (correct)   [f] flip (wrong — adds to eval)   [d] show description   [s] skip   [q] quit\n")

    kept = flipped = skipped = 0

    with open(eval_path, "a") as eval_f:
        for i, job in enumerate(jobs, 1):
            _print_job(job, i, len(jobs))

            current_result = job.get("_filter_result", "pass")

            while True:
                key = input("\n  → ").strip().lower()
                if key == "d":
                    desc = job.get("description", "(no description)")
                    print(f"\n{_c('Full description:', 'bold')}\n")
                    print(desc)
                    print()
                    continue
                if key in ("k", "f", "s", "q"):
                    break
                print("  Enter k / f / d / s / q")

            if key == "q":
                print("\nQuitting review.")
                break
            elif key == "s":
                skipped += 1
                continue
            elif key == "k":
                kept += 1
            elif key == "f":
                flipped += 1
                correct_pass = current_result == "trash"  # flipping trash → correct is pass
                job_id = job.get("id", job.get("job_id", str(uuid.uuid4())))

                if job_id in labeled:
                    print(_c("  (already in eval suite — skipping duplicate)", "dim"))
                else:
                    # Capture the correct classification for fine-tuning quality
                    agent_cls = job.get("_remote_analysis", {}).get("remote_classification", "unclear")
                    print(f"\n  Agent said: {_c(agent_cls, 'yellow')}  — what's the correct classification?")
                    for idx, cls in enumerate(_CLASSIFICATIONS, 1):
                        print(f"    {idx}. {cls}")
                    print(f"    enter — keep agent's classification ({agent_cls})")
                    while True:
                        cls_input = input("  Correct classification: ").strip()
                        if cls_input == "":
                            correct_cls = agent_cls
                            break
                        if cls_input.isdigit() and 1 <= int(cls_input) <= len(_CLASSIFICATIONS):
                            correct_cls = _CLASSIFICATIONS[int(cls_input) - 1]
                            break
                        print("  Enter a number 1-8 or press enter to keep the agent's classification.")

                    notes = input("  Notes (optional): ").strip()
                    record = {
                        "sample_id": job_id,
                        "title": job.get("title", ""),
                        "company": job.get("company", ""),
                        "description": job.get("description", ""),
                        "expected_classification": correct_cls,
                        "expected_should_pass_filter": correct_pass,
                        "expected_travel_days_range": None,
                        "notes": notes or f"[review flip] agent said {current_result} / {agent_cls}",
                    }
                    eval_f.write(json.dumps(record) + "\n")
                    eval_f.flush()
                    labeled.add(job_id)
                    print(_c("  ✓ Added to eval suite", "green"))

    print(f"\n{'━' * 70}")
    print(f"Review complete — {kept} kept · {flipped} flipped → eval · {skipped} skipped")


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

def _cmd_export(args) -> None:
    from agents.remote_filter.utils import _PROMPT

    eval_path = DATA_EVAL / "remote_filter_eval.jsonl"
    if not eval_path.exists():
        log.error("No eval records found at %s — run 'label' or 'review' first", eval_path)
        sys.exit(1)

    records = []
    with open(eval_path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    if not records:
        log.error("Eval file is empty")
        sys.exit(1)

    out_path = DATA_EVAL / "remote_filter_finetune.jsonl"
    skipped = 0
    written = 0

    with open(out_path, "w") as out_f:
        for rec in records:
            description = rec.get("description", "").strip()
            if not description:
                skipped += 1
                continue

            # Build the correct RemoteAnalysis JSON the model should have produced.
            # We have the human-verified classification and pass/fail verdict.
            # Reasoning comes from notes if available; confidence is "high" since
            # a human verified this record.
            travel_range = rec.get("expected_travel_days_range")
            travel_mid = None
            if travel_range and len(travel_range) == 2:
                travel_mid = (travel_range[0] + travel_range[1]) // 2

            reasoning = rec.get("notes", "").strip()
            if not reasoning or reasoning.startswith("[review flip]"):
                reasoning = f"Human-verified classification: {rec['expected_classification']}."

            correct_analysis = {
                "remote_classification": rec["expected_classification"],
                "estimated_travel_days_per_year": travel_mid,
                "travel_description": None,
                "location_restrictions": [],
                "requires_relocation": False,
                "requires_local_presence": not rec["expected_should_pass_filter"] and rec["expected_classification"] in ("onsite_disguised", "hybrid"),
                "confidence": "high",
                "reasoning": reasoning,
            }

            example = {
                "messages": [
                    {"role": "system", "content": _PROMPT},
                    {"role": "user", "content": description},
                    {"role": "assistant", "content": json.dumps(correct_analysis)},
                ]
            }
            out_f.write(json.dumps(example) + "\n")
            written += 1

    log.info("Exported %d training examples → %s  (%d skipped — no description)", written, out_path, skipped)
    print(f"\nFine-tuning dataset: {out_path}")
    print(f"  {written} examples ready  |  {skipped} skipped (no description)")
    print("\nTo upload to OpenAI:")
    print(f"  openai api fine_tuning.jobs.create -t {out_path} -m gpt-4o-mini")


# ---------------------------------------------------------------------------
# Subcommand registration
# ---------------------------------------------------------------------------

def add_subcommands(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("remote-filter", help="Analyze job postings for remote work policy")
    agent_sub = p.add_subparsers(dest="agent_command", metavar="COMMAND")
    agent_sub.required = True

    # label
    label_p = agent_sub.add_parser("label", help="Interactively label jobs from data/raw/ for the eval suite")
    label_p.set_defaults(func=_cmd_label)

    # export
    export_p = agent_sub.add_parser("export", help="Export eval suite as OpenAI fine-tuning JSONL")
    export_p.set_defaults(func=_cmd_export)

    # review
    review_p = agent_sub.add_parser("review", help="Interactively review agent pass/trash decisions")
    review_p.add_argument("--bucket", default="trash", choices=["pass", "trash", "all"],
                          help="Which bucket to review (default: trash — most likely to have errors)")
    review_p.set_defaults(func=_cmd_review)

    # run
    run_p = agent_sub.add_parser("run", help="Run the remote-filter agent on raw job data")
    run_p.add_argument("--input", default=str(DATA_RAW), metavar="DIR",
                       help=f"Directory of JSONL files to process (default: {DATA_RAW})")
    run_p.add_argument("--max-travel", default="quarterly",
                       choices=["none", "quarterly", "monthly"], dest="max_travel")
    run_p.add_argument("--unclear-routing", default="pass",
                       choices=["pass", "reject"], dest="unclear_routing")
    run_p.add_argument("--location", default="USA",
                       help="Your location for restriction checks (default: USA)")
    run_p.set_defaults(func=_cmd_run)
