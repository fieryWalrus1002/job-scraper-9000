import importlib
import importlib.util
import json
from pathlib import Path

from agents.skills_fit.models import SkillsFitAnalysis


REPO_ROOT = Path(__file__).parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_skills_fit.py"


def load_script_module():
    return importlib.reload(importlib.import_module("agents.skills_fit.runner"))


def load_wrapper_module():
    spec = importlib.util.spec_from_file_location("run_skills_fit_script", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


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


def existing_output_row(
    dedup_hash: str,
    *,
    score: int | None,
    failure_reason: str | None = None,
    title: str = "Existing",
) -> dict:
    metadata: dict = {"run_id": "prior_run"}
    if failure_reason is not None:
        metadata["failure_reason"] = failure_reason
    record: dict = {
        "dedup_hash": dedup_hash,
        "title": title,
        "company": "ExistingCo",
        "location": "Remote",
        "metadata": metadata,
    }
    if score is not None:
        record["ai_fit"] = {
            "fit_score": score,
            "confidence": "high",
            "score_rationale": f"Existing rationale for {title}",
            "top_matches": [],
            "gaps": [],
            "hard_concerns": [],
            "core_job_duties": [],
        }
    return record


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
        usage_callback=None,
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
        "cache_hits": 0,
        "cache_misses": 4,
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
    assert alpha["ai_fit"]["fit_score"] == 5
    assert alpha["ai_fit"]["score_rationale"] == "Rationale for Alpha"
    assert alpha["ai_fit"]["top_matches"] == ["match-Alpha"]
    assert alpha["ai_fit"]["gaps"] == ["gap-Alpha"]
    assert alpha["ai_fit"]["hard_concerns"] == ["concern-Alpha"]
    assert alpha["ai_fit"]["confidence"] == "high"
    assert alpha["metadata"]["run_id"] == "skillsfit_fixed"
    assert alpha["metadata"]["profile_version"] == "test-v1"
    assert alpha["metadata"]["profile_hash"].startswith("sha256:")
    assert alpha["metadata"]["provider"] == "ollama"
    assert alpha["metadata"]["model"] == "qwen2.5:14b"
    assert alpha["metadata"]["temperature"] == 0.3
    assert alpha["metadata"]["prompt_file"] == str(prompt_path)
    assert alpha["metadata"]["input_source"] == "local_candidate"
    assert alpha["metadata"]["input_path"] == str(
        Path("data/local") / run_date / "local_jobs.jsonl"
    )

    missing_description = rows[3]
    assert missing_description.get("ai_fit") is None
    assert missing_description["metadata"]["failure_reason"] == "missing_description"

    agent_failed = rows[4]
    assert agent_failed.get("ai_fit") is None
    assert agent_failed["metadata"]["failure_reason"] == "agent_failed"


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
    assert rows[0]["ai_fit"]["fit_score"] == 4
    assert rows[0]["metadata"]["input_source"] == "remote_filter_pass"
    assert rows[0]["metadata"]["input_path"] == str(remote_input)

    runs = read_jsonl(tmp_path / "data/run_telemetry/runs.jsonl")
    assert len(runs) == 1
    assert runs[0]["run_date"] is None
    assert runs[0]["input"]["path"] == str(remote_input)
    assert runs[0]["outputs"][0]["path"] == str(output)
    assert runs[0]["extras"]["path_overrides"] == {
        "remote_input": True,
        "local_input": True,
        "output": True,
    }


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


def test_run_skills_fit_reuses_existing_processed_rows_and_drops_stale_ones(
    tmp_path, monkeypatch
):
    module = load_script_module()
    monkeypatch.chdir(tmp_path)

    config_path = tmp_path / "config/agent/skills_fit.yml"
    profile_path = tmp_path / "config/profile/candidate_profile.yml"
    prompt_path = tmp_path / "prompts/skills_fit/system_prompt.txt"
    remote_input = tmp_path / "data/filtered/2026-05-23/remote_filter_pass.jsonl"
    output_path = tmp_path / "data/scored/2026-05-23/skills_fit_scored.jsonl"
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
    write_jsonl(
        output_path,
        [
            existing_output_row("hash-a", score=5, title="Alpha"),
            existing_output_row("hash-stale", score=4, title="Stale"),
        ],
    )

    seen_titles: list[str] = []

    def fake_analyze(*args, title=None, **kwargs):
        assert title is not None
        seen_titles.append(title)
        return analysis(3, title)

    monkeypatch.setattr(module, "SKILLS_FIT_PROMPT_PATH", prompt_path)
    monkeypatch.setattr(module, "analyze_skills_fit", fake_analyze)
    monkeypatch.setattr(module, "generate_run_id", lambda prefix=None: "resume_run")
    monkeypatch.setattr(
        module,
        "get_git_metadata",
        lambda: {
            "commit": "abc123def456",
            "dirty": False,
            "timestamp": "2026-05-23T12:00:00+00:00",
        },
    )

    summary = module.run_skills_fit(run_date="2026-05-23", config_path=config_path)

    assert summary["scored_successfully"] == 1
    assert seen_titles == ["Beta"]

    rows = [json.loads(line) for line in output_path.read_text().splitlines()]
    assert [row["dedup_hash"] for row in rows] == ["hash-a", "hash-b"]
    assert rows[0]["metadata"]["run_id"] == "prior_run"
    assert rows[1]["metadata"]["run_id"] == "resume_run"


def test_run_skills_fit_treats_failure_reason_rows_as_processed(tmp_path, monkeypatch):
    module = load_script_module()
    monkeypatch.chdir(tmp_path)

    config_path = tmp_path / "config/agent/skills_fit.yml"
    profile_path = tmp_path / "config/profile/candidate_profile.yml"
    prompt_path = tmp_path / "prompts/skills_fit/system_prompt.txt"
    remote_input = tmp_path / "data/filtered/2026-05-23/remote_filter_pass.jsonl"
    output_path = tmp_path / "data/scored/2026-05-23/skills_fit_scored.jsonl"
    write_config(config_path)
    write_profile(profile_path)
    write_prompt(prompt_path)
    write_jsonl(
        remote_input,
        [{"dedup_hash": "hash-a", "title": "Alpha", "description": "alpha"}],
    )
    write_jsonl(
        output_path,
        [existing_output_row("hash-a", score=None, failure_reason="agent_failed")],
    )

    monkeypatch.setattr(module, "SKILLS_FIT_PROMPT_PATH", prompt_path)
    monkeypatch.setattr(
        module,
        "analyze_skills_fit",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not run")),
    )

    summary = module.run_skills_fit(run_date="2026-05-23", config_path=config_path)

    assert summary["scored_successfully"] == 0
    rows = [json.loads(line) for line in output_path.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["metadata"]["failure_reason"] == "agent_failed"


def test_run_skills_fit_uses_analysis_cache_across_outputs(tmp_path, monkeypatch):
    module = load_script_module()
    monkeypatch.chdir(tmp_path)

    config_path = tmp_path / "config/agent/skills_fit.yml"
    profile_path = tmp_path / "config/profile/candidate_profile.yml"
    prompt_path = tmp_path / "prompts/skills_fit/system_prompt.txt"
    remote_input = tmp_path / "data/filtered/2026-05-23/remote_filter_pass.jsonl"
    output_a = tmp_path / "data/scored/2026-05-23/skills_fit_scored_a.jsonl"
    output_b = tmp_path / "data/scored/2026-05-23/skills_fit_scored_b.jsonl"
    write_config(config_path)
    write_profile(profile_path)
    write_prompt(prompt_path)
    write_jsonl(
        remote_input,
        [{"dedup_hash": "hash-a", "title": "Alpha", "description": "alpha"}],
    )

    call_count = 0

    def fake_analyze(*args, title=None, **kwargs):
        nonlocal call_count
        call_count += 1
        assert title is not None
        return analysis(4, title)

    monkeypatch.setattr(module, "SKILLS_FIT_PROMPT_PATH", prompt_path)
    monkeypatch.setattr(module, "analyze_skills_fit", fake_analyze)

    summary_a = module.run_skills_fit(
        run_date="2026-05-23", config_path=config_path, output=output_a
    )
    summary_b = module.run_skills_fit(
        run_date="2026-05-23", config_path=config_path, output=output_b
    )

    assert call_count == 1
    assert summary_a["cache_hits"] == 0
    assert summary_a["cache_misses"] == 1
    assert summary_b["cache_hits"] == 1
    assert summary_b["cache_misses"] == 0


def test_run_skills_fit_retries_unscored_rows_without_failure_reason_and_warns_on_malformed_existing_output(
    tmp_path, monkeypatch, caplog
):
    module = load_script_module()
    monkeypatch.chdir(tmp_path)

    config_path = tmp_path / "config/agent/skills_fit.yml"
    profile_path = tmp_path / "config/profile/candidate_profile.yml"
    prompt_path = tmp_path / "prompts/skills_fit/system_prompt.txt"
    remote_input = tmp_path / "data/filtered/2026-05-23/remote_filter_pass.jsonl"
    output_path = tmp_path / "data/scored/2026-05-23/skills_fit_scored.jsonl"
    write_config(config_path)
    write_profile(profile_path)
    write_prompt(prompt_path)
    write_jsonl(
        remote_input,
        [{"dedup_hash": "hash-a", "title": "Alpha", "description": "alpha"}],
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "not json\n" + json.dumps(existing_output_row("hash-a", score=None)) + "\n",
        encoding="utf-8",
    )

    seen_titles: list[str] = []

    def fake_analyze(*args, title=None, **kwargs):
        assert title is not None
        seen_titles.append(title)
        return analysis(4, title)

    monkeypatch.setattr(module, "SKILLS_FIT_PROMPT_PATH", prompt_path)
    monkeypatch.setattr(module, "analyze_skills_fit", fake_analyze)

    summary = module.run_skills_fit(run_date="2026-05-23", config_path=config_path)

    assert summary["scored_successfully"] == 1
    assert seen_titles == ["Alpha"]
    assert "Skipping malformed existing output line 1" in caplog.text
    rows = [json.loads(line) for line in output_path.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["ai_fit"]["fit_score"] == 4


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
    assert rows[0]["ai_fit"]["fit_score"] == 5


def test_run_skills_fit_writes_run_tracker_record(tmp_path, monkeypatch):
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
            {"dedup_hash": "hash-b", "title": "No Description", "description": ""},
        ],
    )

    def fake_analyze(*args, title=None, usage_callback=None, **kwargs):
        if usage_callback is not None:
            usage_callback(
                {
                    "input_tokens": 100,
                    "cached_input_tokens": 20,
                    "output_tokens": 50,
                }
            )
        assert title is not None
        return analysis(5, title)

    monkeypatch.setattr(module, "SKILLS_FIT_PROMPT_PATH", prompt_path)
    monkeypatch.setattr(module, "analyze_skills_fit", fake_analyze)
    monkeypatch.setattr(
        module, "generate_run_id", lambda prefix=None: "skillsfit_tracker"
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

    summary = module.run_skills_fit(run_date="2026-05-23", config_path=config_path)

    assert summary["run_id"] == "skillsfit_tracker"
    runs = read_jsonl(tmp_path / "data/run_telemetry/runs.jsonl")
    assert len(runs) == 1

    run = runs[0]
    assert run["run_id"] == "skillsfit_tracker"
    assert run["component"] == "skills_fit"
    assert run["run_type"] == "production"
    assert run["run_date"] == "2026-05-23"
    assert run["input"] == {
        "path": "data/filtered/2026-05-23/remote_filter_pass.jsonl",
        "record_count": 2,
        "dedup_dropped": 0,
        "deduped_record_count": 2,
    }
    assert run["config"]["agent_config_path"] == str(config_path)
    assert run["config"]["agent_config_hash"].startswith("sha256:")
    assert run["config"]["prompt_path"] == str(prompt_path)
    assert run["config"]["prompt_hash"].startswith("sha256:")
    assert run["config"]["profile_version"] == "test-v1"
    assert run["config"]["profile_hash"].startswith("sha256:")
    assert run["llm"]["provider"] == "openai"
    assert run["llm"]["model"] == "gpt-4o-mini"
    assert run["llm"]["temperature"] == 0.1
    assert run["llm"]["calls_made"] == 1
    assert run["llm"]["calls_failed"] == 0
    assert run["llm"]["input_tokens_total"] == 100
    assert run["llm"]["input_tokens_cached"] == 20
    assert run["llm"]["output_tokens_total"] == 50
    assert run["cache"] == {
        "path": "data/cache/skills_fit_analyses.jsonl",
        "hits": 0,
        "misses": 1,
        "hit_rate": 0.0,
    }
    assert {output["label"] for output in run["outputs"]} == {
        "scored_rows",
        "scored_successfully",
        "missing_description",
    }
    assert run["outputs"][0]["path"] == "data/scored/2026-05-23/skills_fit_scored.jsonl"
    assert run["outputs"][0]["record_count"] == 2
    assert run["extras"]["remote_loaded"] == 2
    assert run["extras"]["local_loaded"] == 0
    assert run["extras"]["existing_output_loaded"] == 0
    assert run["extras"]["skipped_missing_description"] == 1
    assert run["extras"]["failed_agent"] == 0
    assert run["cost"]["estimated_total"] is not None


def test_run_skills_fit_writes_run_tracker_record_on_interrupt(tmp_path, monkeypatch):
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

    def fake_analyze(*args, title=None, usage_callback=None, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1 and usage_callback is not None:
            usage_callback(
                {
                    "input_tokens": 90,
                    "cached_input_tokens": 10,
                    "output_tokens": 40,
                }
            )
        if call_count == 2:
            raise KeyboardInterrupt
        assert title is not None
        return analysis(5, title)

    monkeypatch.setattr(module, "SKILLS_FIT_PROMPT_PATH", prompt_path)
    monkeypatch.setattr(module, "analyze_skills_fit", fake_analyze)
    monkeypatch.setattr(
        module, "generate_run_id", lambda prefix=None: "skillsfit_interrupt"
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

    try:
        module.run_skills_fit(run_date="2026-05-23", config_path=config_path)
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError("expected KeyboardInterrupt")

    runs = read_jsonl(tmp_path / "data/run_telemetry/runs.jsonl")
    assert len(runs) == 1

    run = runs[0]
    assert run["run_id"] == "skillsfit_interrupt"
    assert run["events"]["failure_count"] == 1
    assert any("Interrupted" in note for note in run["events"]["notable"])
    assert any("KeyboardInterrupt" in note for note in run["events"]["notable"])
    assert run["outputs"][0]["record_count"] == 1
    assert run["cache"]["hits"] == 0
    assert run["cache"]["misses"] == 2
    assert run["llm"]["calls_made"] == 2


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


def test_script_wrapper_reexports_runner_main(monkeypatch):
    calls: list[list[str] | None] = []

    def fake_main(argv=None):
        calls.append(argv)
        return 7

    runner = importlib.import_module("agents.skills_fit.runner")
    monkeypatch.setattr(runner, "main", fake_main)

    module = load_wrapper_module()

    assert module.main(["--run-date", "2026-05-23"]) == 7
    assert calls == [["--run-date", "2026-05-23"]]
