import json
from unittest.mock import MagicMock

import pytest
import requests

from job_scraper.skip_list import is_permanent, load, record


def _http_error(status_code: int) -> requests.HTTPError:
    response = MagicMock()
    response.status_code = status_code
    req = MagicMock()
    req.url = "https://api.lever.co/v0/postings/apple?mode=json"
    exc = requests.HTTPError(f"{status_code} Client Error", response=response)
    exc.request = req
    return exc


# ---------------------------------------------------------------------------
# load()
# ---------------------------------------------------------------------------

def test_load_returns_empty_dict_when_file_missing(tmp_path):
    assert load(tmp_path / "missing.json") == {}


def test_load_returns_existing_records(tmp_path):
    p = tmp_path / "failures.json"
    p.write_text(json.dumps({"lever:apple": {"error": "404", "url": "", "failed_at": "2026-01-01"}}))
    result = load(p)
    assert "lever:apple" in result


# ---------------------------------------------------------------------------
# record()
# ---------------------------------------------------------------------------

def test_record_creates_file(tmp_path):
    p = tmp_path / "sub" / "failures.json"
    record("lever:apple", _http_error(404), path=p)
    assert p.exists()


def test_record_writes_source_name(tmp_path):
    p = tmp_path / "failures.json"
    record("lever:apple", _http_error(404), path=p)
    data = json.loads(p.read_text())
    assert "lever:apple" in data


def test_record_captures_url(tmp_path):
    p = tmp_path / "failures.json"
    record("lever:apple", _http_error(404), path=p)
    data = json.loads(p.read_text())
    assert "lever.co" in data["lever:apple"]["url"]


def test_record_captures_failed_at(tmp_path):
    p = tmp_path / "failures.json"
    record("lever:apple", _http_error(404), path=p)
    data = json.loads(p.read_text())
    assert "failed_at" in data["lever:apple"]


def test_record_appends_without_overwriting_existing(tmp_path):
    p = tmp_path / "failures.json"
    record("lever:apple", _http_error(404), path=p)
    record("ashby:google", _http_error(404), path=p)
    data = json.loads(p.read_text())
    assert "lever:apple" in data
    assert "ashby:google" in data


def test_record_updates_existing_entry(tmp_path):
    p = tmp_path / "failures.json"
    record("lever:apple", _http_error(404), path=p)
    record("lever:apple", _http_error(403), path=p)
    data = json.loads(p.read_text())
    assert "403" in data["lever:apple"]["error"]


# ---------------------------------------------------------------------------
# is_permanent()
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("code", [403, 404, 410])
def test_is_permanent_true_for_permanent_codes(code):
    assert is_permanent(_http_error(code)) is True


@pytest.mark.parametrize("code", [429, 500, 502, 503])
def test_is_permanent_false_for_transient_codes(code):
    assert is_permanent(_http_error(code)) is False


def test_is_permanent_false_for_non_http_error():
    assert is_permanent(ConnectionError("timeout")) is False
