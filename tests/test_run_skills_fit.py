import importlib.util
import json
from pathlib import Path

from agents.skills_fit.models import SkillsFitAnalysis


REPO_ROOT = Path(__file__).parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_skills_fit.py"


def load_script_module():
    spec = importlib.util.spec_from_file_location("run_skills_fit_script", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n")


def write_config(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """
llm:
  provider: openai
  model: gpt-4o-mini
  temperature: 0.1
profile_file: config/profile/candidate_profile.yml
""".strip()
        + "\n",
        encoding="utf-8",
    )


def write_profile(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """
profile_version: test-v1
summary: Test profile
core_skills:
  - Python
constraints:
  - Remote only
""".strip()
        + "\n",
        encoding="utf-8",
    )


def write_prompt(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("You are a skills-fit scorer.\n", encoding="utf-8")


def analysis(score: int, title: str) -> SkillsFitAnalysis:
    return SkillsFitAnalysis(
        fit_score=score,
        confidence="high",
        score_rationale=f"Rationale for {title}",
        top_matches=[f"match-{title}"],
        gaps=[f"gap-{title}"],
        hard_concerns=[f"concern-{title}"],
    )


def test_run_skills_fit_partitioned_mode_dedupes_sorts_and_enriches(
    tmp_path, monkeypatch
):
    module = load_script_module()
    monkeypatch.chdir(tmp_path)

    config_path = tmp_path / "config/agent/skills_fit.yml"
    profile_path = tmp_path / "config/profile/candidate_profile.yml"
    prompt_path = tmp_path / "prompts/skills_fit/system_prompt.txt"
    write_config(config_path)
    write_profile(profile_path)
    write_prompt(prompt_path)

    run_date = "2026-05-23"
    remote_input = tmp_path / "data/filtered" / run_date / "remote_filter_pass.jsonl"
    local_input = tmp_path / "data/local" / run_date / "local_jobs.jsonl"
    write_jsonl(
        remote_input,
        [
            {
                "dedup_hash": "hash-b",
                "title": "Beta",
                "description": "beta description",
                "company": "Acme",
            },
            {
                "dedup_hash": "hash-a",
                "title": "Alpha",
                "description": "short",
                "company": "Acme",
            },
            {
                "dedup_hash": "hash-d",
                "title": "No Description",
                "description": "",
                "company": "Acme",
            },
            {
                "dedup_hash": "hash-e",
                "title": "Agent Fail",
                "description": "agent fail description",
                "company": "Acme",
            },
        ],
    )
    write_jsonl(
        local_input,
        [
            {
                "dedup_hash": "hash-a",
                "title": "Alpha",
                "description": "this is the longer alpha description",
                "company": "LocalCo",
            },
            {
                "dedup_hash": "hash-c",
                "title": "Charlie",
                "description": "charlie description",
                "company": "LocalCo",
            },
        ],
    )

    seen_calls: list[dict] = []

    def fake_analyze(
        job_description,
        *,
        candidate_profile,
        title=None,
        location=None,
        llm_config=None,
        prompt_path=None,
        max_retries=2,
    ):
        seen_calls.append(
            {
                "description": job_description,
                "title": title,
                "profile_version": candidate_profile.get("profile_version"),
                "llm_config": dict(llm_config or {}),
                "prompt_path": str(prompt_path),
            }
        )
        if title == "Agent Fail":
            return None
        if title == "Alpha":
            return analysis(5, title)
        if title == "Beta":
            return analysis(5, title)
        if title == "Charlie":
            return analysis(3, title)
        raise AssertionError(f"unexpected title: {title}")

    monkeypatch.setattr(module, "SKILLS_FIT_PROMPT_PATH", prompt_path)
    monkeypatch.setattr(module, "analyze_skills_fit", fake_analyze)
    monkeypatch.setattr(
        module, "generate_run_id", lambda prefix=None: "skillsfit_fixed"
    )
    monkeypatch.setattr(
        module,
        "get_git_metadata",
        lambda: {
            "commit": "abc123def456",
            "dirty": False,
            "timestamp": "2026-05-23T12:00:00+00:00",
        },
    )

    summary = module.run_skills_fit(
        run_date=run_date,
        config_path=config_path,
        provider="ollama",
        model="qwen2.5:14b",
        temperature=0.3,
    )

    assert summary == {
        "run_id": "skillsfit_fixed",
        "remote_loaded": 4,
        "local_loaded": 2,
        "merged_before_dedupe": 6,
        "merged_after_dedupe": 5,
        "deduped": 1,
        "scored_successfully": 3,
        "skipped_missing_description": 1,
        "failed_agent": 1,
        "output_path": f"data/scored/{run_date}/skills_fit_scored.jsonl",
    }

    assert len(seen_calls) == 4
    alpha_calls = [call for call in seen_calls if call["title"] == "Alpha"]
    assert len(alpha_calls) == 1
    assert alpha_calls[0]["description"] == "this is the longer alpha description"
    assert alpha_calls[0]["profile_version"] == "test-v1"
    assert alpha_calls[0]["llm_config"] == {
        "provider": "ollama",
        "model": "qwen2.5:14b",
        "temperature": 0.3,
    }
    assert alpha_calls[0]["prompt_path"] == str(prompt_path)

    output_path = tmp_path / summary["output_path"]
    rows = [json.loads(line) for line in output_path.read_text().splitlines()]
    assert [row["dedup_hash"] for row in rows] == [
        "hash-a",
        "hash-b",
        "hash-c",
        "hash-d",
        "hash-e",
    ]

    alpha = rows[0]
    assert alpha["company"] == "LocalCo"
    assert alpha["_skills_fit_score"] == 5
    assert alpha["_skills_fit_rationale"] == "Rationale for Alpha"
    assert alpha["_skills_fit_top_matches"] == ["match-Alpha"]
    assert alpha["_skills_fit_gaps"] == ["gap-Alpha"]
    assert alpha["_skills_fit_hard_concerns"] == ["concern-Alpha"]
    assert alpha["_skills_fit_confidence"] == "high"
    assert alpha["_skills_fit_analysis"]["fit_score"] == 5
    assert alpha["_skills_fit_input_source"] == "local_candidate"
    assert alpha["_skills_fit_metadata"]["run_id"] == "skillsfit_fixed"
    assert alpha["_skills_fit_metadata"]["profile_version"] == "test-v1"
    assert alpha["_skills_fit_metadata"]["profile_hash"].startswith("sha256:")
    assert alpha["_skills_fit_metadata"]["provider"] == "ollama"
    assert alpha["_skills_fit_metadata"]["model"] == "qwen2.5:14b"
    assert alpha["_skills_fit_metadata"]["temperature"] == 0.3
    assert alpha["_skills_fit_metadata"]["prompt_file"] == str(prompt_path)
    assert alpha["_skills_fit_metadata"]["input_source"] == "local_candidate"
    assert alpha["_skills_fit_metadata"]["input_path"] == str(
        Path("data/local") / run_date / "local_jobs.jsonl"
    )

    missing_description = rows[3]
    assert missing_description["_skills_fit_score"] is None
    assert missing_description["_skills_fit_analysis"] is None
    assert missing_description["_skills_fit_top_matches"] == []
    assert (
        missing_description["_skills_fit_metadata"]["failure_reason"]
        == "missing_description"
    )

    agent_failed = rows[4]
    assert agent_failed["_skills_fit_score"] is None
    assert agent_failed["_skills_fit_analysis"] is None
    assert agent_failed["_skills_fit_gaps"] == []
    assert agent_failed["_skills_fit_metadata"]["failure_reason"] == "agent_failed"


def test_run_skills_fit_override_mode_works_without_run_date(tmp_path, monkeypatch):
    module = load_script_module()
    monkeypatch.chdir(tmp_path)

    config_path = tmp_path / "config/agent/skills_fit.yml"
    profile_path = tmp_path / "config/profile/candidate_profile.yml"
    prompt_path = tmp_path / "prompts/skills_fit/system_prompt.txt"
    remote_input = tmp_path / "custom/remote.jsonl"
    local_input = tmp_path / "custom/local.jsonl"
    output = tmp_path / "custom/output.jsonl"
    write_config(config_path)
    write_profile(profile_path)
    write_prompt(prompt_path)
    write_jsonl(
        remote_input,
        [
            {
                "dedup_hash": "hash-z",
                "title": "Zulu",
                "description": "zulu description",
            }
        ],
    )

    monkeypatch.setattr(module, "SKILLS_FIT_PROMPT_PATH", prompt_path)
    monkeypatch.setattr(module, "generate_run_id", lambda prefix=None: "override_run")
    monkeypatch.setattr(
        module,
        "get_git_metadata",
        lambda: {
            "commit": "deadbeef",
            "dirty": True,
            "timestamp": "2026-05-23T13:00:00+00:00",
        },
    )
    monkeypatch.setattr(
        module,
        "analyze_skills_fit",
        lambda *args, **kwargs: analysis(4, "Zulu"),
    )

    summary = module.run_skills_fit(
        config_path=config_path,
        remote_input=remote_input,
        local_input=local_input,
        output=output,
    )

    assert summary["remote_loaded"] == 1
    assert summary["local_loaded"] == 0
    assert summary["output_path"] == str(output)

    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["dedup_hash"] == "hash-z"
    assert rows[0]["_skills_fit_score"] == 4
    assert rows[0]["_skills_fit_metadata"]["input_source"] == "remote_filter_pass"
    assert rows[0]["_skills_fit_metadata"]["input_path"] == str(remote_input)


def test_resolve_paths_explicit_overrides_beat_run_date():
    module = load_script_module()

    resolved = module.resolve_paths(
        run_date="2026-05-23",
        remote_input="custom/remote.jsonl",
        local_input="custom/local.jsonl",
        output="custom/output.jsonl",
    )

    assert resolved.remote_input == Path("custom/remote.jsonl")
    assert resolved.local_input == Path("custom/local.jsonl")
    assert resolved.output == Path("custom/output.jsonl")


def test_run_skills_fit_aborts_when_any_record_is_missing_dedup_hash(
    tmp_path, monkeypatch
):
    module = load_script_module()
    monkeypatch.chdir(tmp_path)

    config_path = tmp_path / "config/agent/skills_fit.yml"
    profile_path = tmp_path / "config/profile/candidate_profile.yml"
    prompt_path = tmp_path / "prompts/skills_fit/system_prompt.txt"
    remote_input = tmp_path / "data/filtered/2026-05-23/remote_filter_pass.jsonl"
    write_config(config_path)
    write_profile(profile_path)
    write_prompt(prompt_path)
    write_jsonl(
        remote_input,
        [{"title": "Broken", "description": "missing dedup hash"}],
    )

    monkeypatch.setattr(module, "SKILLS_FIT_PROMPT_PATH", prompt_path)
    monkeypatch.setattr(
        module,
        "analyze_skills_fit",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not run")),
    )

    try:
        module.run_skills_fit(run_date="2026-05-23", config_path=config_path)
    except ValueError as exc:
        assert "dedup_hash" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_run_skills_fit_limit_trims_deduped_records(tmp_path, monkeypatch):
    module = load_script_module()
    monkeypatch.chdir(tmp_path)

    config_path = tmp_path / "config/agent/skills_fit.yml"
    profile_path = tmp_path / "config/profile/candidate_profile.yml"
    prompt_path = tmp_path / "prompts/skills_fit/system_prompt.txt"
    remote_input = tmp_path / "data/filtered/2026-05-23/remote_filter_pass.jsonl"
    write_config(config_path)
    write_profile(profile_path)
    write_prompt(prompt_path)
    write_jsonl(
        remote_input,
        [
            {"dedup_hash": "hash-a", "title": "Alpha", "description": "alpha"},
            {"dedup_hash": "hash-b", "title": "Beta", "description": "beta"},
            {"dedup_hash": "hash-c", "title": "Charlie", "description": "charlie"},
        ],
    )

    seen_titles: list[str] = []

    def fake_analyze(*args, title=None, **kwargs):
        assert title is not None
        seen_titles.append(title)
        return analysis(4, title)

    monkeypatch.setattr(module, "SKILLS_FIT_PROMPT_PATH", prompt_path)
    monkeypatch.setattr(module, "analyze_skills_fit", fake_analyze)
    monkeypatch.setattr(module, "generate_run_id", lambda prefix=None: "limit_run")
    monkeypatch.setattr(
        module,
        "get_git_metadata",
        lambda: {
            "commit": "cafebabe",
            "dirty": False,
            "timestamp": "2026-05-23T14:00:00+00:00",
        },
    )

    summary = module.run_skills_fit(
        run_date="2026-05-23", config_path=config_path, limit=2
    )

    assert summary["scored_successfully"] == 2
    assert summary["merged_after_dedupe"] == 2
    assert seen_titles == ["Alpha", "Beta"]

    output_path = tmp_path / summary["output_path"]
    rows = [json.loads(line) for line in output_path.read_text().splitlines()]
    assert [row["dedup_hash"] for row in rows] == ["hash-a", "hash-b"]


def test_run_skills_fit_requires_run_date_without_full_path_overrides(
    tmp_path, monkeypatch
):
    module = load_script_module()
    monkeypatch.chdir(tmp_path)

    config_path = tmp_path / "config/agent/skills_fit.yml"
    profile_path = tmp_path / "config/profile/candidate_profile.yml"
    prompt_path = tmp_path / "prompts/skills_fit/system_prompt.txt"
    write_config(config_path)
    write_profile(profile_path)
    write_prompt(prompt_path)

    monkeypatch.setattr(module, "SKILLS_FIT_PROMPT_PATH", prompt_path)

    try:
        module.run_skills_fit(config_path=config_path)
    except ValueError as exc:
        assert "--run-date is required" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_run_skills_fit_fails_when_config_file_is_missing(tmp_path, monkeypatch):
    module = load_script_module()
    monkeypatch.chdir(tmp_path)

    prompt_path = tmp_path / "prompts/skills_fit/system_prompt.txt"
    monkeypatch.setattr(module, "SKILLS_FIT_PROMPT_PATH", prompt_path)

    try:
        module.run_skills_fit(
            config_path=tmp_path / "config/agent/missing.yml",
            remote_input=tmp_path / "custom/remote.jsonl",
            local_input=tmp_path / "custom/local.jsonl",
            output=tmp_path / "custom/output.jsonl",
        )
    except FileNotFoundError as exc:
        assert "Config file not found" in str(exc)
    else:
        raise AssertionError("expected FileNotFoundError")


def test_run_skills_fit_fails_when_profile_file_is_missing(tmp_path, monkeypatch):
    module = load_script_module()
    monkeypatch.chdir(tmp_path)

    config_path = tmp_path / "config/agent/skills_fit.yml"
    prompt_path = tmp_path / "prompts/skills_fit/system_prompt.txt"
    remote_input = tmp_path / "data/filtered/2026-05-23/remote_filter_pass.jsonl"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        """
llm:
  provider: openai
  model: gpt-4o-mini
profile_file: config/profile/missing_profile.yml
""".strip()
        + "\n",
        encoding="utf-8",
    )
    write_prompt(prompt_path)
    write_jsonl(
        remote_input,
        [{"dedup_hash": "hash-a", "title": "Alpha", "description": "alpha"}],
    )

    monkeypatch.setattr(module, "SKILLS_FIT_PROMPT_PATH", prompt_path)
    monkeypatch.setattr(
        module,
        "analyze_skills_fit",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not run")),
    )

    try:
        module.run_skills_fit(run_date="2026-05-23", config_path=config_path)
    except FileNotFoundError as exc:
        assert "Profile file not found" in str(exc)
    else:
        raise AssertionError("expected FileNotFoundError")


def test_run_skills_fit_fails_when_prompt_file_is_missing(tmp_path, monkeypatch):
    module = load_script_module()
    monkeypatch.chdir(tmp_path)

    config_path = tmp_path / "config/agent/skills_fit.yml"
    profile_path = tmp_path / "config/profile/candidate_profile.yml"
    remote_input = tmp_path / "data/filtered/2026-05-23/remote_filter_pass.jsonl"
    write_config(config_path)
    write_profile(profile_path)
    write_jsonl(
        remote_input,
        [{"dedup_hash": "hash-a", "title": "Alpha", "description": "alpha"}],
    )

    missing_prompt = tmp_path / "prompts/skills_fit/missing_prompt.txt"
    monkeypatch.setattr(module, "SKILLS_FIT_PROMPT_PATH", missing_prompt)
    monkeypatch.setattr(
        module,
        "analyze_skills_fit",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not run")),
    )

    try:
        module.run_skills_fit(run_date="2026-05-23", config_path=config_path)
    except FileNotFoundError as exc:
        assert "Prompt file not found" in str(exc)
    else:
        raise AssertionError("expected FileNotFoundError")


def test_run_skills_fit_flushes_partial_results_on_keyboard_interrupt(
    tmp_path, monkeypatch
):
    module = load_script_module()
    monkeypatch.chdir(tmp_path)

    config_path = tmp_path / "config/agent/skills_fit.yml"
    profile_path = tmp_path / "config/profile/candidate_profile.yml"
    prompt_path = tmp_path / "prompts/skills_fit/system_prompt.txt"
    remote_input = tmp_path / "data/filtered/2026-05-23/remote_filter_pass.jsonl"
    write_config(config_path)
    write_profile(profile_path)
    write_prompt(prompt_path)
    write_jsonl(
        remote_input,
        [
            {"dedup_hash": "hash-a", "title": "Alpha", "description": "alpha"},
            {"dedup_hash": "hash-b", "title": "Beta", "description": "beta"},
        ],
    )

    call_count = 0

    def fake_analyze(*args, title=None, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise KeyboardInterrupt
        assert title is not None
        return analysis(5, title)

    monkeypatch.setattr(module, "SKILLS_FIT_PROMPT_PATH", prompt_path)
    monkeypatch.setattr(module, "analyze_skills_fit", fake_analyze)
    monkeypatch.setattr(
        module,
        "get_git_metadata",
        lambda: {
            "commit": "abc123def456",
            "dirty": False,
            "timestamp": "2026-05-23T12:00:00+00:00",
        },
    )

    try:
        module.run_skills_fit(run_date="2026-05-23", config_path=config_path)
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError("expected KeyboardInterrupt")

    output_path = tmp_path / "data/scored/2026-05-23/skills_fit_scored.jsonl"
    rows = [json.loads(line) for line in output_path.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["dedup_hash"] == "hash-a"
    assert rows[0]["_skills_fit_score"] == 5


def test_main_returns_one_on_fail_fast_error(tmp_path, monkeypatch):
    module = load_script_module()
    monkeypatch.chdir(tmp_path)

    exit_code = module.main(["--config", "config/agent/missing.yml"])

    assert exit_code == 1


def test_main_returns_130_on_keyboard_interrupt(tmp_path, monkeypatch):
    module = load_script_module()
    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(
        module,
        "run_skills_fit",
        lambda **kwargs: (_ for _ in ()).throw(KeyboardInterrupt),
    )

    exit_code = module.main(["--run-date", "2026-05-23"])

    assert exit_code == 130
