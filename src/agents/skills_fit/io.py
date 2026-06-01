import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def load_existing_output_records(path: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return records

    with path.open(encoding="utf-8") as f:
        for line_number, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                log.warning(
                    "Skipping malformed existing output line %d in %s: %s",
                    line_number,
                    path,
                    exc,
                )
                continue
            if not isinstance(record, dict):
                log.warning(
                    "Skipping non-object existing output line %d in %s",
                    line_number,
                    path,
                )
                continue
            dedup_hash = record.get("dedup_hash")
            if not dedup_hash:
                log.warning(
                    "Skipping existing output line %d in %s with missing dedup_hash",
                    line_number,
                    path,
                )
                continue
            records[str(dedup_hash)] = record
    return records


def rank_key(record: dict[str, Any]) -> tuple[bool, int, str]:
    ai_fit = record.get("ai_fit") or {}
    score = ai_fit.get("fit_score") if isinstance(ai_fit, dict) else None
    return (score is None, -(score or 0), record["dedup_hash"])


def write_output(records: list[dict[str, Any]], output_path: Path) -> None:
    records.sort(key=rank_key)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def is_processed_output_record(record: dict[str, Any]) -> bool:
    metadata = record.get("metadata")
    if not isinstance(metadata, dict):
        return False
    ai_fit = record.get("ai_fit") or {}
    if isinstance(ai_fit, dict) and ai_fit.get("fit_score") is not None:
        return True
    return metadata.get("failure_reason") is not None


def load_tagged_inputs(
    *, remote_input: Path, local_input: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not remote_input.exists():
        raise FileNotFoundError(f"Remote input file not found: {remote_input}")

    remote_records = [
        {
            **record,
            "__input_source": "remote_filter_pass",
            "__input_path": str(remote_input),
        }
        for record in read_jsonl(remote_input)
    ]

    local_records: list[dict[str, Any]] = []
    if local_input.exists():
        local_records = [
            {
                **record,
                "__input_source": "local_candidate",
                "__input_path": str(local_input),
            }
            for record in read_jsonl(local_input)
        ]
    else:
        log.info("Local input not found; continuing without it: %s", local_input)

    return remote_records, local_records


def validate_dedup_hashes(records: list[dict[str, Any]]) -> None:
    missing_examples: list[str] = []
    missing_count = 0
    for i, record in enumerate(records):
        if record.get("dedup_hash"):
            continue
        missing_count += 1
        if len(missing_examples) < 5:
            label = record.get("title") or record.get("source_url") or f"index={i}"
            missing_examples.append(str(label))
    if missing_count:
        examples = ", ".join(missing_examples)
        raise ValueError(
            "Input contract failure: every record must include dedup_hash "
            f"({missing_count} missing; examples: {examples})"
        )
