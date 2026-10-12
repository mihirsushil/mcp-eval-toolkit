from uuid import UUID

import pytest

from mcp_eval_toolkit.evidence import canonical_hash, write_json
from mcp_eval_toolkit.reporting import read_json, report
from test_scoring import CASES, TOOLS, trace


@pytest.fixture
def evidence(tmp_path):
    cases = [CASES["stats_population"], CASES["clarify_player_stats"]]
    suite = {"version": 1, "split": "dev", "cases": [case.model_dump() for case in cases]}
    settings = {"provider": "fixture", "model": "fixture"}
    write_json(
        tmp_path / "manifest.json",
        {
            "kind": "scripted-demo",
            "repeats": 1,
            "evaluation_suite_sha256": canonical_hash(suite),
            "tool_sha256": {variant: canonical_hash(TOOLS) for variant in ("A", "B")},
            "requested_model_settings": settings,
        },
    )
    write_json(tmp_path / "suite.json", suite)
    for variant in ("A", "B"):
        write_json(tmp_path / f"tools-{variant}.json", TOOLS)
        for index, case in enumerate(cases):
            run_id = str(UUID(int=index + (1 if variant == "A" else 3)))
            calls = [("compute_stats", {})] if case.expected.action == "call" else []
            observed = trace(calls, text="Please supply a player hash.")
            observed["upstream_run_id"] = run_id
            observed["messages"][0]["parts"][0]["content"] = case.query()
            write_json(tmp_path / "traces" / f"{run_id}.json", observed)
            write_json(
                tmp_path / "runs" / f"{case.id}-0-{variant}.json",
                {
                    "case_id": case.id,
                    "variant": variant,
                    "repeat": 0,
                    "trace_sha256": canonical_hash(observed),
                    "result": {"id": run_id, "status": "completed", "model_settings": settings},
                },
            )
    return tmp_path


def test_complete_report_separates_deterministic_and_review_results(evidence):
    summary = report(evidence, draws=100)
    assert summary["complete"] is True
    assert summary["scored_attempts"] == 4
    assert summary["pending_reviews"] == 2
    assert summary["paired"]["delta"] == 0
    assert "SCRIPTED DEMO" in (evidence / "scored/report.md").read_text()
    verdicts = read_json(evidence / "scored/scores.json")
    assert sum(row["final_pass"] is None for row in verdicts) == 2


def test_missing_attempt_excludes_entire_case_cluster(evidence):
    (evidence / "runs/stats_population-0-B.json").unlink()
    summary = report(evidence, draws=100)
    assert summary["complete"] is False
    assert summary["error_or_missing_attempts"] == 1
    assert summary["paired"]["cases"] == 1
    assert summary["paired"]["delta_interval"] is None


def test_missing_trace_is_an_error_not_a_pass(evidence):
    (evidence / "traces" / f"{UUID(int=1)}.json").unlink()
    assert report(evidence, draws=100)["error_or_missing_attempts"] == 1


def test_duplicate_run_is_rejected(evidence):
    write_json(
        evidence / "runs/duplicate.json", read_json(evidence / "runs/stats_population-0-A.json")
    )
    with pytest.raises(ValueError, match="duplicate run"):
        report(evidence, draws=100)


@pytest.mark.parametrize("target", ["suite.json", "tools-A.json"])
def test_changed_input_snapshot_is_rejected(evidence, target):
    write_json(evidence / target, {})
    with pytest.raises(ValueError, match="checksum mismatch"):
        report(evidence, draws=100)


def test_modified_trace_is_rejected(evidence):
    write_json(evidence / "traces" / f"{UUID(int=1)}.json", {"messages": []})
    with pytest.raises(ValueError, match="trace checksum"):
        report(evidence, draws=100)


def test_mismatched_model_is_rejected(evidence):
    path = evidence / "runs/stats_population-0-A.json"
    record = read_json(path)
    record["result"]["model_settings"]["model"] = "other-model"
    write_json(path, record)
    with pytest.raises(ValueError, match="model/provider"):
        report(evidence, draws=100)


def test_reviews_are_bound_to_case_and_trace(evidence):
    report(evidence, draws=100)
    labels = read_json(evidence / "scored/review-template.json")
    for label in labels:
        label.update(
            decision="fail",
            reviewer="unit-test fixture",
            rationale="Fixture text fails this test rubric.",
        )
    path = evidence / "reviews.json"
    write_json(path, labels)
    summary = report(evidence, path, draws=100)
    assert summary["pending_reviews"] == 0
    assert (
        sum(row["final_pass"] is False for row in read_json(evidence / "scored/scores.json")) == 2
    )
    labels[0]["trace_sha256"] = "stale"
    write_json(path, labels)
    with pytest.raises(ValueError, match="stale review"):
        report(evidence, path, draws=100)


def test_incomplete_review_template_is_rejected(evidence):
    report(evidence, draws=100)
    path = evidence / "reviews.json"
    write_json(path, read_json(evidence / "scored/review-template.json"))
    with pytest.raises(ValueError):
        report(evidence, path, draws=100)
