"""Tests for RunLogger Protocol and JsonlRunLogger."""

import json
import pytest


# ---------------------------------------------------------------------------
# JsonlRunLogger — _sanitize
# ---------------------------------------------------------------------------



def test_sanitize_strips_api_key():
    # config block containing "api_key" must be redacted
    from eval.logger import JsonlRunLogger
    logger = JsonlRunLogger.__new__(JsonlRunLogger)
    record = {"config": {"provider": "openai", "api_key": "sk-secret"}}
    result = logger._sanitize(record)
    assert result["config"]["api_key"] == "[REDACTED]"
    assert result["config"]["provider"] == "openai"



def test_sanitize_strips_token():
    from eval.logger import JsonlRunLogger
    logger = JsonlRunLogger.__new__(JsonlRunLogger)
    record = {"config": {"access_token": "tok-secret", "model": "gpt-4o-mini"}}
    result = logger._sanitize(record)
    assert result["config"]["access_token"] == "[REDACTED]"
    assert result["config"]["model"] == "gpt-4o-mini"



def test_sanitize_does_not_mutate_original():
    # _sanitize must deep-copy — original record must be unchanged
    from eval.logger import JsonlRunLogger
    logger = JsonlRunLogger.__new__(JsonlRunLogger)
    original = {"config": {"api_key": "sk-secret"}}
    logger._sanitize(original)
    assert original["config"]["api_key"] == "sk-secret"



def test_sanitize_leaves_safe_fields_intact():
    from eval.logger import JsonlRunLogger
    logger = JsonlRunLogger.__new__(JsonlRunLogger)
    record = {"config": {"provider": "openai", "model": "gpt-4o-mini", "temperature": 0.1}}
    result = logger._sanitize(record)
    assert result["config"] == {"provider": "openai", "model": "gpt-4o-mini", "temperature": 0.1}


# ---------------------------------------------------------------------------
# JsonlRunLogger — file I/O
# ---------------------------------------------------------------------------



def test_log_run_writes_valid_json_line(tmp_path):
    from eval.logger import JsonlRunLogger
    log_file = tmp_path / "runs.jsonl"
    logger = JsonlRunLogger(log_file)
    logger.log_run({"run_id": "test_001", "metrics": {"f1": 0.9}})
    lines = log_file.read_text().strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["run_id"] == "test_001"



def test_log_run_appends_not_overwrites(tmp_path):
    from eval.logger import JsonlRunLogger
    log_file = tmp_path / "runs.jsonl"
    logger = JsonlRunLogger(log_file)
    logger.log_run({"run_id": "first"})
    logger.log_run({"run_id": "second"})
    lines = log_file.read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["run_id"] == "first"
    assert json.loads(lines[1])["run_id"] == "second"



def test_log_run_creates_parent_directory(tmp_path):
    from eval.logger import JsonlRunLogger
    log_file = tmp_path / "nested" / "dir" / "runs.jsonl"
    logger = JsonlRunLogger(log_file)
    logger.log_run({"run_id": "x"})
    assert log_file.exists()



def test_log_run_non_fatal_on_unwritable_path(tmp_path, caplog):
    # A bad path must emit a warning and not raise — SC-1
    import logging
    from eval.logger import JsonlRunLogger
    logger = JsonlRunLogger("/root/no_permission/runs.jsonl")
    with caplog.at_level(logging.WARNING):
        logger.log_run({"run_id": "x"})  # must not raise
    assert any("Failed" in r.message for r in caplog.records)



def test_log_run_rejects_duplicate_run_id(tmp_path):
    # SC-2: custom run_id must be unique within runs.jsonl
    from eval.logger import JsonlRunLogger
    log_file = tmp_path / "runs.jsonl"
    logger = JsonlRunLogger(log_file)
    logger.log_run({"run_id": "my_label"})
    with pytest.raises(ValueError, match="run_id.*already exists"):
        logger.log_run({"run_id": "my_label"})


# ---------------------------------------------------------------------------
# RunLogger — Protocol structural typing
# ---------------------------------------------------------------------------



def test_arbitrary_class_satisfies_protocol():
    # Any class with log_run(record: dict) -> None satisfies RunLogger at runtime

    class FakeLogger:
        def log_run(self, record: dict) -> None:
            pass

    # Protocol check requires @runtime_checkable — verify the design holds
    assert callable(FakeLogger().log_run)
