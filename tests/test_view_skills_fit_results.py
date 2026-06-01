import importlib.util
import io
from pathlib import Path


REPO_ROOT = Path(__file__).parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "view_skills_fit_results.py"


def load_script_module():
    spec = importlib.util.spec_from_file_location(
        "view_skills_fit_results_script", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_resolve_input_path_prefers_explicit_override():
    module = load_script_module()

    resolved = module.resolve_input_path(
        run_date="2026-05-24", input_path="custom/scored.jsonl"
    )

    assert resolved == Path("custom/scored.jsonl")


def test_resolve_input_path_uses_partitioned_run_date():
    module = load_script_module()

    resolved = module.resolve_input_path(run_date="2026-05-24", input_path=None)

    assert resolved == Path("data/scored/2026-05-24/skills_fit_scored.jsonl")


def test_view_results_renders_ranked_table_and_limit(tmp_path, monkeypatch):
    module = load_script_module()
    monkeypatch.chdir(tmp_path)

    scored_path = tmp_path / "data/scored/2026-05-24/skills_fit_scored.jsonl"
    write_text(
        scored_path,
        "\n".join(
            [
                '{"ai_fit": {"fit_score": 5, "hard_concerns": []}, "title": "Alpha", "company": "Acme", "location": "Remote"}',
                '{"ai_fit": {"fit_score": 4, "hard_concerns": ["onsite"]}, "title": "Beta", "company": "BetaCo", "location": "Seattle"}',
                '{"title": "Gamma", "company": "GammaCo", "location": null}',
            ]
        )
        + "\n",
    )

    out = io.StringIO()
    summary = module.view_results(run_date="2026-05-24", limit=2, out=out)

    rendered = out.getvalue()
    assert summary == {
        "input_path": "data/scored/2026-05-24/skills_fit_scored.jsonl",
        "row_count": 3,
        "displayed_count": 2,
    }
    assert "RANK" in rendered
    assert "Alpha" in rendered
    assert "Beta" in rendered
    assert "Gamma" not in rendered
    assert "BLOCKERS" in rendered


def test_view_results_show_rationale_prints_details(tmp_path, monkeypatch):
    module = load_script_module()
    monkeypatch.chdir(tmp_path)

    scored_path = tmp_path / "custom/scored.jsonl"
    write_text(
        scored_path,
        '{"ai_fit": {"fit_score": 5, "score_rationale": "Strong overlap", "hard_concerns": ["Hybrid"]}, "title": "Alpha", "company": "Acme", "location": "Remote"}\n',
    )

    out = io.StringIO()
    module.view_results(input_path=scored_path, show_rationale=True, out=out)

    rendered = out.getvalue()
    assert "rationale: Strong overlap" in rendered
    assert "hard concerns: Hybrid" in rendered


def test_view_results_requires_run_date_or_input(tmp_path, monkeypatch):
    module = load_script_module()
    monkeypatch.chdir(tmp_path)

    try:
        module.view_results()
    except ValueError as exc:
        assert "--run-date or --input is required" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_view_results_warns_and_skips_malformed_lines(tmp_path, monkeypatch, caplog):
    module = load_script_module()
    monkeypatch.chdir(tmp_path)

    scored_path = tmp_path / "custom/scored.jsonl"
    write_text(
        scored_path,
        "{"
        '"ai_fit": {"fit_score": 5, "hard_concerns": []}, "title": "Alpha", "company": "Acme", "location": "Remote"}'
        "\nnot json\n"
        '{"ai_fit": {"fit_score": 4, "hard_concerns": ["Visa"]}, "title": "Beta", "company": "BetaCo", "location": "NYC"}\n',
    )

    out = io.StringIO()
    summary = module.view_results(input_path=scored_path, out=out)

    assert summary["row_count"] == 2
    assert "Skipping malformed JSONL line 2" in caplog.text
    rendered = out.getvalue()
    assert "Alpha" in rendered
    assert "Beta" in rendered


def test_main_warns_on_empty_file_and_exits_zero(tmp_path, monkeypatch, caplog):
    module = load_script_module()
    monkeypatch.chdir(tmp_path)

    scored_path = tmp_path / "custom/empty.jsonl"
    write_text(scored_path, "")

    exit_code = module.main(["--input", str(scored_path)])

    assert exit_code == 0
    assert "No scored rows found" in caplog.text


def test_main_returns_one_when_input_file_is_missing(tmp_path, monkeypatch, caplog):
    module = load_script_module()
    monkeypatch.chdir(tmp_path)

    exit_code = module.main(["--input", "custom/missing.jsonl"])

    assert exit_code == 1
    assert "Scored input file not found" in caplog.text


def test_parse_args_rejects_invalid_limit():
    module = load_script_module()

    try:
        module.parse_args(["--input", "x.jsonl", "--limit", "0"])
    except SystemExit as exc:
        assert exc.code != 0
    else:
        raise AssertionError("expected SystemExit")
