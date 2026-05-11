import json

from job_scraper.company_boards import load, merge, save, boards_for


def test_load_missing_file_returns_empty(tmp_path):
    assert load(tmp_path / "missing.json") == {}


def test_load_returns_existing(tmp_path):
    p = tmp_path / "boards.json"
    p.write_text(json.dumps({"anthropic": ["greenhouse"]}))
    assert load(p) == {"anthropic": ["greenhouse"]}


def test_load_corrupt_file_returns_empty(tmp_path):
    p = tmp_path / "boards.json"
    p.write_text("not json {{")
    assert load(p) == {}


def test_save_creates_parent_dirs(tmp_path):
    p = tmp_path / "sub" / "boards.json"
    save({"anthropic": ["greenhouse"]}, p)
    assert p.exists()


def test_save_roundtrips(tmp_path):
    p = tmp_path / "boards.json"
    db = {"anthropic": ["greenhouse"], "mistral": ["ashby"]}
    save(db, p)
    assert load(p) == db


def test_save_sorts_keys(tmp_path):
    p = tmp_path / "boards.json"
    save({"zebra": ["lever"], "alpha": ["ashby"]}, p)
    raw = p.read_text()
    assert raw.index("alpha") < raw.index("zebra")


def test_merge_adds_new_company():
    db = {"anthropic": ["greenhouse"]}
    result = merge(db, {"mistral": ["ashby"]})
    assert result["mistral"] == ["ashby"]
    assert result["anthropic"] == ["greenhouse"]


def test_merge_appends_new_board_to_existing():
    db = {"stripe": ["lever"]}
    result = merge(db, {"stripe": ["greenhouse"]})
    assert set(result["stripe"]) == {"lever", "greenhouse"}


def test_merge_deduplicates():
    db = {"stripe": ["lever"]}
    result = merge(db, {"stripe": ["lever"]})
    assert result["stripe"] == ["lever"]


def test_merge_does_not_mutate_original():
    db = {"anthropic": ["greenhouse"]}
    merge(db, {"mistral": ["ashby"]})
    assert "mistral" not in db


def test_boards_for_known_company():
    db = {"anthropic": ["greenhouse"]}
    assert boards_for("anthropic", db) == ["greenhouse"]


def test_boards_for_unknown_company():
    assert boards_for("unknown", {}) == []
