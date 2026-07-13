import logging
from types import SimpleNamespace

import pytest

from utils import batch_api


def _counts(completed=0, total=0, failed=0):
    return SimpleNamespace(completed=completed, total=total, failed=failed)


def _batch(batch_id="batch-1", status="completed", output_file_id=None):
    return SimpleNamespace(
        id=batch_id,
        status=status,
        output_file_id=output_file_id,
        error_file_id=None,
        request_counts=_counts(),
    )


class _FakeFiles:
    def __init__(self, content_text=""):
        self._content_text = content_text
        self.created_purposes: list[str] = []

    def create(self, file, purpose):
        self.created_purposes.append(purpose)
        return SimpleNamespace(id="file-123")

    def content(self, file_id):
        assert file_id == "out-file"
        return SimpleNamespace(text=self._content_text)


class _FakeBatches:
    def __init__(self, retrieve_statuses=None, created_batch=None):
        self._statuses = list(retrieve_statuses or [])
        self._created_batch = created_batch or _batch(status="validating")
        self.create_kwargs: dict | None = None
        self.retrieve_calls = 0

    def create(self, **kwargs):
        self.create_kwargs = kwargs
        return self._created_batch

    def retrieve(self, batch_id):
        self.retrieve_calls += 1
        status = self._statuses.pop(0)
        return _batch(batch_id=batch_id, status=status)


class _MultiFakeBatches:
    """Retrieve returns the next status for each id from its own sequence."""

    def __init__(self, status_seqs: dict[str, list[str]]):
        self._seqs = {k: list(v) for k, v in status_seqs.items()}
        self.retrieve_calls = 0

    def retrieve(self, batch_id):
        self.retrieve_calls += 1
        status = self._seqs[batch_id].pop(0)
        return _batch(batch_id=batch_id, status=status)


class _FakeClient:
    def __init__(self, files=None, batches=None):
        self.files = files or _FakeFiles()
        self.batches = batches or _FakeBatches()


def test_terminal_statuses_are_the_non_advancing_set():
    assert batch_api.TERMINAL_STATUSES == frozenset(
        {"completed", "failed", "expired", "cancelled"}
    )


def test_upload_and_create_batch_returns_batch_and_file_ids(tmp_path):
    request_file = tmp_path / "requests.jsonl"
    request_file.write_text('{"custom_id": "job-0"}\n')
    batches = _FakeBatches(created_batch=_batch(batch_id="batch-xyz"))
    client = _FakeClient(files=_FakeFiles(), batches=batches)

    batch_id, file_id = batch_api.upload_and_create_batch(client, request_file)

    assert batch_id == "batch-xyz"
    assert file_id == "file-123"
    assert client.files.created_purposes == ["batch"]
    assert batches.create_kwargs == {
        "input_file_id": "file-123",
        "endpoint": batch_api.BATCH_ENDPOINT,
        "completion_window": batch_api.COMPLETION_WINDOW,
    }


def test_poll_until_done_loops_until_terminal(monkeypatch):
    monkeypatch.setattr(batch_api.time, "sleep", lambda _s: None)
    batches = _FakeBatches(retrieve_statuses=["validating", "in_progress", "completed"])
    client = _FakeClient(batches=batches)

    batch = batch_api.poll_until_done(client, "batch-1", poll_interval=0)

    assert batch.status == "completed"
    assert batches.retrieve_calls == 3


def test_poll_all_until_done_drops_terminal_batches(monkeypatch):
    monkeypatch.setattr(batch_api.time, "sleep", lambda _s: None)
    batches = _MultiFakeBatches({"b1": ["in_progress", "completed"], "b2": ["failed"]})
    client = _FakeClient(batches=batches)

    result = batch_api.poll_all_until_done(client, ["b1", "b2"], poll_interval=0)

    assert set(result) == {"b1", "b2"}
    assert result["b1"].status == "completed"
    assert result["b2"].status == "failed"
    assert batches.retrieve_calls == 3


def test_poll_all_until_done_empty_input_never_retrieves_or_sleeps(monkeypatch):
    sleep_calls = []
    monkeypatch.setattr(
        batch_api.time, "sleep", lambda seconds: sleep_calls.append(seconds)
    )
    batches = _MultiFakeBatches({})
    client = _FakeClient(batches=batches)

    result = batch_api.poll_all_until_done(client, [], poll_interval=0)

    assert result == {}
    assert batches.retrieve_calls == 0
    assert sleep_calls == []


def test_poll_all_until_done_logs_per_tick_progress(monkeypatch, caplog):
    monkeypatch.setattr(batch_api.time, "sleep", lambda _s: None)
    batches = _MultiFakeBatches({"b1": ["in_progress", "completed"], "b2": ["failed"]})
    client = _FakeClient(batches=batches)
    caplog.set_level(logging.INFO, logger=batch_api.log.name)

    batch_api.poll_all_until_done(client, ["b1", "b2"], poll_interval=0)

    progress_lines = [
        record.message
        for record in caplog.records
        if "of" in record.message and "terminal" in record.message
    ]
    assert progress_lines
    assert progress_lines[-1] == "2 of 2 batch(es) terminal (0 still running)"


def test_download_results_returns_output_text():
    client = _FakeClient(files=_FakeFiles(content_text="line1\nline2\n"))
    batch = _batch(status="completed", output_file_id="out-file")

    assert batch_api.download_results(client, batch) == "line1\nline2\n"


def test_download_results_raises_when_not_completed():
    client = _FakeClient()
    batch = _batch(status="failed", output_file_id="out-file")

    with pytest.raises(RuntimeError, match="status=failed"):
        batch_api.download_results(client, batch)


def test_download_results_raises_when_output_file_missing():
    client = _FakeClient()
    batch = _batch(status="completed", output_file_id=None)

    with pytest.raises(RuntimeError, match="output_file_id is missing"):
        batch_api.download_results(client, batch)
