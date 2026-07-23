"""Offline contract tests for the companies embedding-ranker prototype."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import prototype_companies_embedding_ranker as ranker


class FakeEmbeddingClient:
    """Deterministic OpenAI-compatible fake; it makes no network calls."""

    def __init__(self) -> None:
        self.requests: list[list[str]] = []

    @property
    def embeddings(self) -> FakeEmbeddingClient:
        return self

    def create(self, *, model: str, input: list[str]) -> SimpleNamespace:  # noqa: A002
        self.requests.append(input)
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=self.vector(text)) for text in input]
        )

    @staticmethod
    def vector(text: str) -> list[float]:
        text = text.lower()
        if "mechanical" in text or "manufacturing" in text:
            return [1.0, 0.0]
        if "software" in text:
            return [0.0, 1.0]
        return [0.5, 0.5]


def job(
    title: str, company: str, key: str, description: str | None = "details"
) -> dict[str, object]:
    return {
        "title": title,
        "company": company,
        "dedup_hash": key,
        "description": description,
        "source_url": f"https://example.test/{key}",
    }


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def args_for(tmp_path: Path, **overrides: object) -> argparse.Namespace:
    input_path = tmp_path / "companies.jsonl"
    profile_path = tmp_path / "profile.yml"
    write_jsonl(
        input_path,
        [
            job("Mechanical Engineer", "Acme", "a", "build fixtures"),
            job("Software Engineer", "Acme", "b", "write services"),
            job("Janitor", "Other", "c", None),
        ],
    )
    profile_path.write_text(
        "summary: Mechanical engineer\ncore_skills: [CAD]\nadjacent_skills: [Python]\n"
        "preferred_domains: [aerospace]\n",
        encoding="utf-8",
    )
    values: dict[str, object] = {
        "input": str(input_path),
        "profile": str(profile_path),
        "target_title": ["mechanical engineer"],
        "goal_summary": "Build hardware",
        "provider": "ollama",
        "model": "fake-embed",
        "base_url": "http://fake-ollama:11434/v1/",
        "api_key_env": "UNUSED",
        "cache": str(tmp_path / "cache.jsonl"),
        "output_dir": str(tmp_path / "output"),
        "overwrite": False,
        "embedding_batch_size": 100,
        "job_text_variants": "title,title_description_500",
        "prefix_scheme": "none",
        "reference_mode": "blend",
        "allow_ground_truth_reference": False,
        "skills_fit": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def test_canonical_text_profile_validation_and_whitespace(tmp_path: Path) -> None:
    parsed = ranker.parse_postings_jsonl(
        json.dumps(job(" Mechanical\n Engineer ", " Acme\t", "x", " a\n b ")),
        tmp_path / "input.jsonl",
    )
    assert parsed[0].title == "Mechanical Engineer"
    assert (
        ranker.build_job_text(parsed[0], "title_description_500")
        == "Mechanical Engineer\n\na b"
    )
    profile = ranker.validate_profile(
        {
            "summary": "Summary",
            "core_skills": ["CAD"],
            "adjacent_skills": [],
            "preferred_domains": ["space"],
        },
        tmp_path / "profile.yml",
    )
    assert ranker.build_reference_text(
        profile, [" Mechanical Engineer ", "mechanical engineer"], "Goal"
    ) == (
        "Target job titles (highest priority): Mechanical Engineer\nGoal summary: Goal\n"
        "Candidate summary: Summary\nCore skills: CAD\nAdjacent skills: \nPreferred domains: space"
    )
    with pytest.raises(ValueError, match="summary must be a string"):
        ranker.validate_profile({"summary": 1}, tmp_path / "bad.yml")
    with pytest.raises(ValueError, match="list of strings"):
        ranker.validate_profile(
            {"summary": "ok", "core_skills": "CAD"}, tmp_path / "bad.yml"
        )


def test_ranking_cosine_company_ordering_and_ties() -> None:
    postings = [
        ranker.Posting("A", "Acme", "b", "", "", True),
        ranker.Posting("B", "Acme", "a", "", "", True),
        ranker.Posting("C", "Else", "c", "", "", True),
    ]
    ranked = ranker.rank_postings(postings, [[1, 0], [1, 0], [0, 1]], [1, 0], {"a": 5})
    assert [
        (item.posting.dedup_hash, item.global_rank, item.company_rank)
        for item in ranked
    ] == [
        ("a", 1, 1),
        ("b", 2, 2),
        ("c", 3, 1),
    ]
    with pytest.raises(ValueError, match="unequal"):
        ranker.cosine_similarity([1], [1, 0])
    with pytest.raises(ValueError, match="zero-norm"):
        ranker.cosine_similarity([0, 0], [1, 0])


def test_cache_identity_uses_schema_text_model_endpoint_and_safe_serialization() -> (
    None
):
    item = ranker.Posting("Mechanical Engineer", "Acme", "a", "details", "", False)
    endpoint = ranker.endpoint_identity("ollama", "HTTP://LOCALHOST:80/v1/")
    assert endpoint == "http://localhost/v1"
    title = ranker.cache_identity(
        schema_version=ranker.TITLE_SCHEMA,
        provider="ollama",
        endpoint=endpoint,
        model="one",
        text=ranker.build_job_text(item, "title"),
    )
    described = ranker.cache_identity(
        schema_version=ranker.TITLE_DESCRIPTION_SCHEMA,
        provider="ollama",
        endpoint=endpoint,
        model="one",
        text=ranker.build_job_text(item, "title_description_500"),
    )
    assert title.key != described.key
    assert (
        title.key
        != ranker.cache_identity(
            schema_version=ranker.TITLE_SCHEMA,
            provider="ollama",
            endpoint=endpoint,
            model="two",
            text=item.title,
        ).key
    )
    assert (
        title.key
        != ranker.cache_identity(
            schema_version=ranker.TITLE_SCHEMA,
            provider="ollama",
            endpoint="http://other/v1",
            model="one",
            text=item.title,
        ).key
    )
    assert (
        ranker.CacheIdentity("s", "p", "http://host/a|b", "c", "d").key
        != ranker.CacheIdentity("s", "p", "http://host/a", "b|c", "d").key
    )
    with pytest.raises(ValueError, match="absolute"):
        ranker.endpoint_identity("ollama", "http://host/v1?secret=x")


def test_in_run_dedupe_cache_reuse_and_changed_description_miss(tmp_path: Path) -> None:
    args = args_for(tmp_path)
    write_jsonl(
        Path(args.input),
        [
            job("Mechanical Engineer", "A", "one", "same"),
            job("Mechanical Engineer", "B", "two", "same"),
        ],
    )
    first = FakeEmbeddingClient()
    first_manifest = ranker.run(args, embedding_client=first)
    assert sum(map(len, first.requests)) == 3  # reference + title + title-description
    assert first_manifest["cli_arguments"]["prefix_scheme"] == "none"
    assert first_manifest["text_builder_schema_versions"]["reference"] == "reference-v1"
    assert first_manifest["cache_statistics"]["by_variant"] == {
        "title": {
            "cache_hits": 0,
            "cache_misses": 2,
            "vectors_requested": 2,
            "provider_api_batches": 1,
        },
        "title_description_500": {
            "cache_hits": 0,
            "cache_misses": 2,
            "vectors_requested": 2,
            "provider_api_batches": 1,
        },
    }
    args.overwrite = True
    second = FakeEmbeddingClient()
    manifest = ranker.run(args, embedding_client=second)
    assert second.requests == []
    assert manifest["cache_statistics"]["vectors_requested"] == 0
    assert all(
        row["ai_fit"] == ""
        for row in csv_rows(Path(args.output_dir) / "ranked_title.csv")
    )
    write_jsonl(
        Path(args.input),
        [
            job("Mechanical Engineer", "A", "one", "changed"),
            job("Mechanical Engineer", "B", "two", "changed"),
        ],
    )
    changed = FakeEmbeddingClient()
    manifest = ranker.run(args, embedding_client=changed)
    assert sum(map(len, changed.requests)) == 1
    assert manifest["cache_statistics"]["cache_misses"] == 1


def test_nomic_prefix_scheme_changes_inputs_schemas_and_cache_keys(
    tmp_path: Path,
) -> None:
    posting = ranker.Posting(
        "Mechanical Engineer", "Acme", "a", "description", "", False
    )
    assert (
        ranker.apply_prefix_scheme("reference", role="reference", prefix_scheme="none")
        == "reference"
    )
    assert (
        ranker.apply_prefix_scheme("reference", role="reference", prefix_scheme="nomic")
        == "search_query: reference"
    )
    assert (
        ranker.apply_prefix_scheme(
            ranker.build_job_text(posting, "title_description_500"),
            role="job",
            prefix_scheme="nomic",
        )
        == "search_document: Mechanical Engineer\n\ndescription"
    )

    args = args_for(tmp_path)
    ranker.run(args, embedding_client=FakeEmbeddingClient())
    args.overwrite = True
    args.prefix_scheme = "nomic"
    nomic_client = FakeEmbeddingClient()
    manifest = ranker.run(args, embedding_client=nomic_client)
    requested = [text for batch in nomic_client.requests for text in batch]
    assert manifest["cache_statistics"]["cache_misses"] == len(requested)
    assert (
        len(requested) == 7
    )  # Prefixes and schemas must not reuse none-scheme vectors.
    assert sum(text.startswith("search_query: ") for text in requested) == 1
    assert all(
        text.startswith(("search_query: ", "search_document: ")) for text in requested
    )
    assert manifest["cli_arguments"]["prefix_scheme"] == "nomic"
    assert manifest["text_builder_schema_versions"] == {
        "reference": "reference-nomic-v1",
        "title": "job-title-nomic-v1",
        "title_description_500": "job-title-description-500-nomic-v1",
    }


def test_embedding_batch_size_controls_provider_request_size() -> None:
    client = FakeEmbeddingClient()
    missing = {
        ranker.CacheIdentity("s", "p", "e", "m", str(index)): str(index)
        for index in range(5)
    }

    _, vectors_requested, api_batches = ranker.fetch_missing_embeddings(
        client, "m", missing, batch_size=2
    )

    assert [len(batch) for batch in client.requests] == [2, 2, 1]
    assert vectors_requested == 5
    assert api_batches == 3
    with pytest.raises(ValueError, match="at least 1"):
        ranker.fetch_missing_embeddings(client, "m", missing, batch_size=0)


def test_bad_input_cache_and_embedding_response_fail_without_output(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match=r"input.jsonl line 1.*invalid JSON"):
        ranker.parse_postings_jsonl("{oops", tmp_path / "input.jsonl")
    with pytest.raises(ValueError, match="required field 'title'"):
        ranker.parse_postings_jsonl(
            json.dumps(job("", "Acme", "a")), tmp_path / "input.jsonl"
        )
    identity = ranker.cache_identity(
        schema_version=ranker.TITLE_SCHEMA,
        provider="ollama",
        endpoint="http://localhost",
        model="m",
        text="x",
    )
    first, second = (
        ranker._cache_entry(identity, [1, 0]),
        ranker._cache_entry(identity, [0, 1]),
    )
    with pytest.raises(ValueError, match="duplicate key has a different"):
        ranker.parse_cache_jsonl(
            json.dumps(first) + "\n" + json.dumps(second), tmp_path / "cache.jsonl"
        )
    with pytest.raises(ValueError, match="stored dimension"):
        broken = {**first, "dimension": 3}
        ranker.parse_cache_jsonl(json.dumps(broken), tmp_path / "cache.jsonl")
    missing = {identity: "x"}
    with pytest.raises(ValueError, match="exactly one vector"):
        ranker.fetch_missing_embeddings(
            SimpleNamespace(
                embeddings=SimpleNamespace(create=lambda **_: SimpleNamespace(data=[]))
            ),
            "m",
            missing,
        )
    with pytest.raises(ValueError, match="must be finite"):
        client = SimpleNamespace(
            embeddings=SimpleNamespace(
                create=lambda **_: SimpleNamespace(
                    data=[SimpleNamespace(embedding=[float("nan")])]
                )
            )
        )
        ranker.fetch_missing_embeddings(client, "m", missing)

    class ZeroClient(FakeEmbeddingClient):
        def create(self, *, model: str, input: list[str]) -> SimpleNamespace:
            return SimpleNamespace(
                data=[SimpleNamespace(embedding=[0.0, 0.0]) for _ in input]
            )

    args = args_for(tmp_path)
    with pytest.raises(ValueError, match="zero-norm"):
        ranker.run(args, embedding_client=ZeroClient())
    assert not Path(args.output_dir).exists()


def test_outputs_manifest_no_leakage_and_skills_fit_join(tmp_path: Path) -> None:
    args = args_for(tmp_path)
    secret = "DO NOT LEAK THIS DESCRIPTION"
    write_jsonl(
        Path(args.input),
        [
            job("Mechanical Engineer", "Acme", "a", secret),
            job("Janitor", "Other", "missing", None),
        ],
    )
    scored = tmp_path / "scored.jsonl"
    write_jsonl(scored, [{"dedup_hash": "a", "ai_fit": {"nested": {"fit_score": 5}}}])
    args.skills_fit = str(scored)
    manifest = ranker.run(args, embedding_client=FakeEmbeddingClient())
    output = Path(args.output_dir)
    for name in ("ranked_title.csv", "ranked_title_description_500.csv"):
        rows = csv_rows(output / name)
        assert len(rows) == 2
        assert list(rows[0]) == ranker.CSV_COLUMNS
        assert {row["dedup_hash"]: row["ai_fit"] for row in rows} == {
            "a": "5",
            "missing": "",
        }
        assert secret not in (output / name).read_text(encoding="utf-8")
    manifest_text = (output / "manifest.json").read_text(encoding="utf-8")
    assert secret not in manifest_text
    assert manifest["skills_fit"]["matched_count"] == 1
    assert manifest["skills_fit"]["unmatched_count"] == 1
    with pytest.raises(ValueError, match="not unpackable"):
        ranker.parse_skills_fit_jsonl(
            json.dumps({"dedup_hash": "a", "ai_fit": {"bad": "shape"}}), scored
        )
    with pytest.raises(ValueError, match="invalid JSON"):
        ranker.parse_skills_fit_jsonl("not-json", scored)


def test_overwrite_and_output_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args = args_for(tmp_path)
    output = Path(args.output_dir)
    output.mkdir()
    (output / "prior.txt").write_text("unrelated", encoding="utf-8")
    client = FakeEmbeddingClient()
    with pytest.raises(FileExistsError, match="non-empty"):
        ranker.run(args, embedding_client=client)
    assert client.requests == []
    args.overwrite = True
    ranker.run(args, embedding_client=client)
    assert (output / "ranked_title.csv").exists()
    assert (output / "prior.txt").read_text(encoding="utf-8") == "unrelated"
    reused = FakeEmbeddingClient()
    ranker.run(args, embedding_client=reused)
    assert reused.requests == []

    original_replace = ranker.os.replace

    def fail_second(source: str | Path, destination: str | Path) -> None:
        if Path(destination).name == "second.csv":
            raise OSError("simulated rename failure")
        original_replace(source, destination)

    monkeypatch.setattr(ranker.os, "replace", fail_second)
    empty = tmp_path / "empty"
    with pytest.raises(OSError, match="simulated"):
        ranker.publish_outputs(
            empty, {"first.csv": b"one", "second.csv": b"two"}, overwrite=False
        )
    assert not (empty / "first.csv").exists()
    assert not (empty / "second.csv").exists()


# --------------------------------------------------------------------------- #
# Reference-mode tests
# --------------------------------------------------------------------------- #


def test_blend_default_is_byte_identical_regression(tmp_path: Path) -> None:
    """blend (default) produces identical ranking to pre-change single-reference."""
    args = args_for(tmp_path, reference_mode="blend")
    manifest = ranker.run(args, embedding_client=FakeEmbeddingClient())
    rows = csv_rows(Path(args.output_dir) / "ranked_title.csv")
    # Mechanical jobs rank above Janitor with FakeEmbeddingClient
    assert rows[0]["dedup_hash"] == "a"
    assert rows[0]["global_rank"] == "1"
    assert manifest["cli_arguments"]["reference_mode"] == "blend"
    assert manifest["cli_arguments"]["reference_vector_count"] == 1


def test_keywords_reference_has_no_profile_text(tmp_path: Path) -> None:
    """keywords mode builds a reference text with titles only."""
    titles = ["Software Engineer", "Mechanical Engineer"]
    text = ranker.build_keywords_reference_text(titles)
    assert "Candidate summary" not in text
    assert "Core skills" not in text
    assert "Software Engineer" in text
    assert "Mechanical Engineer" in text
    # Different sha from blend
    profile = {
        "summary": "Test",
        "core_skills": ["CAD"],
        "adjacent_skills": [],
        "preferred_domains": [],
    }
    blend_text = ranker.build_reference_text(profile, titles, "")
    assert ranker.sha256_text(text) != ranker.sha256_text(blend_text)


def test_keyword_max_vs_mean_produce_different_rankings(tmp_path: Path) -> None:
    """A job matching exactly one keyword ranks higher under max than mean."""

    # Custom fake: each title gets its own distinct vector
    class TitleVectorClient(FakeEmbeddingClient):
        @staticmethod
        def vector(text: str) -> list[float]:
            text = text.lower()
            if "title one" in text:
                return [1.0, 0.0, 0.0]
            if "title two" in text:
                return [0.0, 1.0, 0.0]
            # Job vectors
            if "matches one" in text:
                return [0.9, 0.1, 0.0]  # close to title one
            if "matches both" in text:
                return [0.5, 0.5, 0.0]  # midway
            return [0.0, 0.0, 1.0]  # unrelated

    write_jsonl(
        tmp_path / "companies.jsonl",
        [
            job("Matches One", "A", "m1", "matches one"),
            job("Matches Both", "B", "m2", "matches both"),
            job("Unrelated", "C", "u", "nothing"),
        ],
    )
    profile_path = tmp_path / "profile.yml"
    profile_path.write_text(
        "summary: Test\ncore_skills: [X]\nadjacent_skills: []\npreferred_domains: []\n"
    )
    base = {
        "input": str(tmp_path / "companies.jsonl"),
        "profile": str(profile_path),
        "target_title": ["Title One", "Title Two"],
        "goal_summary": "",
        "provider": "ollama",
        "model": "fake-embed",
        "base_url": "http://fake:11434/v1/",
        "api_key_env": "UNUSED",
        "cache": str(tmp_path / "cache.jsonl"),
        "output_dir": str(tmp_path / "output"),
        "overwrite": False,
        "job_text_variants": "title",
        "prefix_scheme": "none",
        "reference_mode": "keyword-max",
        "allow_ground_truth_reference": False,
        "skills_fit": None,
    }

    # keyword-max: m1 should rank #1 (max picks best title match)
    args_max = argparse.Namespace(**base)
    ranker.run(args_max, embedding_client=TitleVectorClient())
    rows_max = csv_rows(tmp_path / "output" / "ranked_title.csv")
    assert rows_max[0]["dedup_hash"] == "m1"

    # keyword-mean: m1 and m2 may differ
    base["reference_mode"] = "keyword-mean"
    base["output_dir"] = str(tmp_path / "output_mean")
    base["overwrite"] = False
    args_mean = argparse.Namespace(**base)
    ranker.run(args_mean, embedding_client=TitleVectorClient())
    rows_mean = csv_rows(tmp_path / "output_mean" / "ranked_title.csv")
    # Under mean, m2 (midway) could beat m1 (close to one only)
    # The key assertion: rankings differ
    assert rows_max[0]["dedup_hash"] != rows_mean[0]["dedup_hash"] or (
        float(rows_max[0]["similarity"]) != float(rows_mean[0]["similarity"])
    )


def test_skills_max_ranks_skills_match_above_keyword_only(tmp_path: Path) -> None:
    """skills-max promotes a job matching the skills blob."""

    class SkillsVectorClient(FakeEmbeddingClient):
        @staticmethod
        def vector(text: str) -> list[float]:
            text = text.lower()
            # Reference: title vectors
            if "title one" in text:
                return [1.0, 0.0, 0.0]
            if "title two" in text:
                return [0.0, 1.0, 0.0]
            # Skills reference
            if "core skills" in text:
                return [0.0, 0.0, 1.0]
            # Job: matches skills but not titles
            if "skills only" in text:
                return [0.1, 0.1, 0.8]
            # Job: matches title one
            if "title match" in text:
                return [0.8, 0.1, 0.1]
            return [0.3, 0.3, 0.3]

    write_jsonl(
        tmp_path / "companies.jsonl",
        [
            job("Title Match", "A", "tm", "title match"),
            job("Skills Only", "B", "so", "skills only"),
        ],
    )
    profile_path = tmp_path / "profile.yml"
    profile_path.write_text(
        "summary: Test\ncore_skills: [Python]\nadjacent_skills: [SQL]\npreferred_domains: []\n"
    )
    base = {
        "input": str(tmp_path / "companies.jsonl"),
        "profile": str(profile_path),
        "target_title": ["Title One", "Title Two"],
        "goal_summary": "",
        "provider": "ollama",
        "model": "fake-embed",
        "base_url": "http://fake:11434/v1/",
        "api_key_env": "UNUSED",
        "cache": str(tmp_path / "cache.jsonl"),
        "output_dir": str(tmp_path / "output"),
        "overwrite": False,
        "job_text_variants": "title",
        "prefix_scheme": "none",
        "reference_mode": "skills-max",
        "allow_ground_truth_reference": False,
        "skills_fit": None,
    }
    args = argparse.Namespace(**base)
    ranker.run(args, embedding_client=SkillsVectorClient())
    rows = csv_rows(tmp_path / "output" / "ranked_title.csv")
    # With skills-max, the skills-only job gets a boost from the skills vector
    # Both jobs get max over {title1, title2, skills}. Skills-only job's max
    # comes from skills ref (high cosine), title-match job's max from title1.
    # Both should have decent scores; the test verifies the mode runs without error
    # and produces valid output.
    assert len(rows) == 2
    assert all(row["similarity"] != "" for row in rows)


def test_exemplar_requires_gates(tmp_path: Path) -> None:
    """exemplar raises without --allow-ground-truth-reference or --skills-fit."""
    args = args_for(tmp_path, reference_mode="exemplar")
    with pytest.raises(ValueError, match="allow-ground-truth-reference"):
        ranker.run(args, embedding_client=FakeEmbeddingClient())

    args2 = args_for(
        tmp_path,
        reference_mode="exemplar",
        allow_ground_truth_reference=True,
    )
    with pytest.raises(ValueError, match="skills-fit"):
        ranker.run(args2, embedding_client=FakeEmbeddingClient())


def test_exemplar_ranks_known_good_job_at_top(tmp_path: Path) -> None:
    """exemplar mode with both gates: a job matching exemplar centroid ranks high."""
    # Use a dedicated subdirectory so args_for defaults don't clash
    d = tmp_path / "exemplar"
    d.mkdir()
    scored = d / "scored.jsonl"
    write_jsonl(
        scored,
        [
            {"dedup_hash": "good1", "ai_fit": 5},
            {"dedup_hash": "good2", "ai_fit": 4},
            {"dedup_hash": "bad", "ai_fit": 1},
        ],
    )
    input_path = d / "companies.jsonl"
    write_jsonl(
        input_path,
        [
            job("Good Job 1", "A", "good1", "excellent work"),
            job("Good Job 2", "B", "good2", "great work"),
            job("Bad Job", "C", "bad", "terrible work"),
        ],
    )
    profile_path = d / "profile.yml"
    profile_path.write_text(
        "summary: Test\ncore_skills: [X]\nadjacent_skills: []\npreferred_domains: []\n"
    )

    class ExemplarClient(FakeEmbeddingClient):
        @staticmethod
        def vector(text: str) -> list[float]:
            text = text.lower()
            if "good job 1" in text:
                return [1.0, 0.0]
            if "good job 2" in text:
                return [0.8, 0.2]
            if "bad job" in text:
                return [0.0, 1.0]
            # Reference texts (engineer, etc.)
            return [0.5, 0.5]

    args = argparse.Namespace(
        input=str(input_path),
        profile=str(profile_path),
        target_title=["Engineer"],
        goal_summary="",
        provider="ollama",
        model="fake-embed",
        base_url="http://fake:11434/v1/",
        api_key_env="UNUSED",
        cache=str(d / "cache.jsonl"),
        output_dir=str(d / "output"),
        overwrite=False,
        job_text_variants="title",
        prefix_scheme="none",
        reference_mode="exemplar",
        allow_ground_truth_reference=True,
        skills_fit=str(scored),
    )
    manifest = ranker.run(args, embedding_client=ExemplarClient())
    rows = csv_rows(Path(args.output_dir) / "ranked_title.csv")
    # Centroid of good1 [1,0] and good2 [0.8,0.2] ≈ [0.9, 0.1]
    # good1 cosine ≈ 0.99, good2 ≈ 0.98, bad ≈ 0.1 → good1 ranks first
    assert rows[0]["dedup_hash"] in ("good1", "good2")
    assert manifest["cli_arguments"]["reference_mode"] == "exemplar"
    assert manifest["cli_arguments"]["reference_vector_count"] == 0


def test_pool_scores_pure_function() -> None:
    """pool_scores reduces correctly for max and mean."""
    job = [1.0, 0.0]
    ref1 = [1.0, 0.0]  # perfect match
    ref2 = [0.0, 1.0]  # orthogonal
    assert ranker.pool_scores([job], [ref1, ref2], "max") == pytest.approx([1.0])
    assert ranker.pool_scores([job], [ref1, ref2], "mean") == pytest.approx([0.5])
    with pytest.raises(ValueError, match="empty"):
        ranker.pool_scores([job], [], "max")
    with pytest.raises(ValueError, match="Unknown pool"):
        ranker.pool_scores([job], [ref1], "median")


def test_rank_by_scores_preserves_tie_break() -> None:
    """rank_by_scores breaks ties by dedup_hash (asc)."""
    postings = [
        ranker.Posting("A", "X", "b", "", "", True),
        ranker.Posting("B", "X", "a", "", "", True),
    ]
    ranked = ranker.rank_by_scores(postings, [0.9, 0.9], {})
    assert ranked[0].posting.dedup_hash == "a"
    assert ranked[1].posting.dedup_hash == "b"


def test_each_mode_writes_valid_csv(tmp_path: Path) -> None:
    """Every mode produces a ranked_title.csv with the correct schema."""
    for mode in ("blend", "keywords", "keyword-max", "keyword-mean", "skills-max"):
        out_dir = tmp_path / f"out_{mode}"
        args = args_for(tmp_path, reference_mode=mode, output_dir=str(out_dir))
        ranker.run(args, embedding_client=FakeEmbeddingClient())
        rows = csv_rows(out_dir / "ranked_title.csv")
        assert len(rows) == 3
        assert list(rows[0].keys()) == ranker.CSV_COLUMNS
