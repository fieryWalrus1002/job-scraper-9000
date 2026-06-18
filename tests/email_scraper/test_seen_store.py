"""Tests for email_scraper.seen_store — the Layer-1 membership cache."""

from email_scraper.seen_store import JsonlSeenStore


def test_add_and_has(tmp_path):
    store = JsonlSeenStore(tmp_path / "seen.jsonl")
    assert not store.has("a")
    store.add("a")
    assert store.has("a")
    assert not store.has("b")


def test_persists_across_instances(tmp_path):
    path = tmp_path / "seen.jsonl"
    JsonlSeenStore(path).add("x")
    # A fresh instance reloads the file.
    assert JsonlSeenStore(path).has("x")


def test_add_is_idempotent(tmp_path):
    path = tmp_path / "seen.jsonl"
    store = JsonlSeenStore(path)
    store.add("dup")
    store.add("dup")
    assert path.read_text().strip().count("\n") == 0  # one line, no trailing dup
    assert JsonlSeenStore(path).has("dup")


def test_missing_file_is_empty(tmp_path):
    assert not JsonlSeenStore(tmp_path / "nope.jsonl").has("anything")


def test_malformed_line_skipped(tmp_path):
    path = tmp_path / "seen.jsonl"
    path.write_text('not json\n{"key": "good"}\n{"no": "key"}\n')
    store = JsonlSeenStore(path)
    assert store.has("good")
