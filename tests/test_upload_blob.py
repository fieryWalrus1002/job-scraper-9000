"""Tests for ``scripts/upload_blob.py`` — the multi-user blob uploader (Phase
15 slice 3).

The ``az`` upload is injected (``upload_fn``) so no test touches Azure; the
work under test is the per-user walk, the flat
``pending/<run_id>__<slug>__scored.jsonl`` blob naming (root-level so the KEDA
scaler counts it), and the loud failure on an empty run.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "upload_blob.py"

RUN_ID = "2026-06-12T1635-overnight"


def load_module():
    spec = importlib.util.spec_from_file_location("upload_blob_script", SCRIPT_PATH)
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


def test_uploads_one_blob_per_user(tmp_path):
    mod = load_module()
    alice = _write_scored(tmp_path, "alice_example_com", "alice@example.com")
    bob = _write_scored(tmp_path, "bob_example_com", "bob@example.com")
    # A sibling _consolidated stage dir must be ignored by the walk.
    (tmp_path / RUN_ID / "_consolidated").mkdir(parents=True)

    calls: list[dict] = []

    def fake_upload(*, account_name, container, blob_name, file_path):
        calls.append(
            {
                "account_name": account_name,
                "container": container,
                "blob_name": blob_name,
                "file_path": Path(file_path),
            }
        )

    names = mod.upload_run(
        run_id=RUN_ID,
        account_name="acct",
        runs_dir=tmp_path,
        upload_fn=fake_upload,
    )

    assert names == [
        f"{RUN_ID}__alice_example_com__scored.jsonl",
        f"{RUN_ID}__bob_example_com__scored.jsonl",
    ]
    # Each upload targets the pending container on the given account, from the
    # user's own scored file.
    assert [c["account_name"] for c in calls] == ["acct", "acct"]
    assert [c["container"] for c in calls] == ["pending", "pending"]
    assert [c["file_path"] for c in calls] == [alice, bob]


def test_custom_container_is_honored(tmp_path):
    mod = load_module()
    _write_scored(tmp_path, "alice_example_com", "alice@example.com")

    calls: list[dict] = []

    mod.upload_run(
        run_id=RUN_ID,
        account_name="acct",
        runs_dir=tmp_path,
        container="staging",
        upload_fn=lambda **kw: calls.append(kw),
    )

    assert calls[0]["container"] == "staging"


def test_raises_loud_when_run_has_no_outputs(tmp_path):
    mod = load_module()
    with pytest.raises(SystemExit, match="No per-user scored files"):
        mod.upload_run(
            run_id="missing",
            account_name="acct",
            runs_dir=tmp_path,
            upload_fn=lambda **kw: None,
        )
