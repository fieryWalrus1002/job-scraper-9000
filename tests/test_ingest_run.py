"""Tests for ``scripts/ingest_run.py`` — the local-dev ingest recipe (Phase 15
slice 4).

The per-file ingest is injected (``ingest_fn``) so no test needs a DB or a
subprocess; the work under test is the per-user walk, the args handed to the
ingest CLI, and the loud failure on an empty run. One test monkeypatches
``subprocess.run`` to lock the actual CLI invocation.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "ingest_run.py"

RUN_ID = "2026-06-12T1635-overnight"


def load_module():
    spec = importlib.util.spec_from_file_location("ingest_run_script", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_scored(runs_dir: Path, slug: str, email: str) -> Path:
    out_dir = runs_dir / RUN_ID / slug / "skills_fit"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "scored.jsonl"
    path.write_text(json.dumps({"dedup_hash": "h1", "user_email": email}) + "\n")
    return path


def test_ingests_each_user_file_in_order(tmp_path):
    mod = load_module()
    alice = _write_scored(tmp_path, "alice_example_com", "alice@example.com")
    bob = _write_scored(tmp_path, "bob_example_com", "bob@example.com")
    # A sibling _consolidated stage dir must be ignored by the walk.
    (tmp_path / RUN_ID / "_consolidated").mkdir(parents=True)

    calls: list[dict] = []

    ingested = mod.ingest_run(
        run_id=RUN_ID,
        runs_dir=tmp_path,
        ingest_fn=lambda **kw: calls.append(kw),
    )

    assert ingested == [alice, bob]
    assert [c["scored_path"] for c in calls] == [alice, bob]
    assert all(c["dry_run"] is False for c in calls)


def test_dry_run_propagates(tmp_path):
    mod = load_module()
    _write_scored(tmp_path, "alice_example_com", "alice@example.com")

    calls: list[dict] = []
    mod.ingest_run(
        run_id=RUN_ID,
        runs_dir=tmp_path,
        dry_run=True,
        ingest_fn=lambda **kw: calls.append(kw),
    )

    assert calls[0]["dry_run"] is True


def test_raises_loud_when_run_has_no_outputs(tmp_path):
    mod = load_module()
    with pytest.raises(SystemExit, match="No per-user scored files"):
        mod.ingest_run(
            run_id="missing",
            runs_dir=tmp_path,
            ingest_fn=lambda **kw: None,
        )


def test_cli_ingest_builds_expected_command(tmp_path, monkeypatch):
    """The default ingest_fn shells to `job-scraper-9000 ingest` with the
    file and --dry-run only when asked."""
    mod = load_module()
    captured: list[list[str]] = []

    def fake_run(cmd, check):
        captured.append(cmd)
        assert check is True

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    scored = tmp_path / "scored.jsonl"
    mod._cli_ingest(scored_path=scored, dry_run=False)
    mod._cli_ingest(scored_path=scored, dry_run=True)

    assert captured[0] == ["job-scraper-9000", "ingest", "--input", str(scored)]
    assert captured[1][-1] == "--dry-run"
