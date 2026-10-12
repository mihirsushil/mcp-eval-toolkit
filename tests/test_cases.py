from pathlib import Path

import pytest
from pydantic import ValidationError

from mcp_eval_toolkit.cases import Call, Expected, Suite, load_suite, select_suite
from mcp_eval_toolkit.runtime import validate_cases, verify_description_only
from mcp_eval_toolkit.tef import adapter_limits, payload

ROOT = Path(__file__).resolve().parents[1]


def test_suite_counts_and_all_tools():
    dev = load_suite(ROOT / "cases/poker/dev.yaml")
    heldout = load_suite(ROOT / "cases/poker/heldout.yaml")
    assert len(dev.cases) == 24
    assert len(heldout.cases) == 6
    assert len({c.id for c in dev.cases + heldout.cases}) == 30
    assert {a.tool for c in dev.cases for a in c.expected.acceptable} == {
        "query_hands",
        "get_hand",
        "compute_stats",
        "compare_positions",
        "find_leaks",
        "session_summary",
    }


def test_holdout_is_not_selected_accidentally():
    with pytest.raises(ValueError, match="final-report"):
        select_suite(ROOT, "heldout")
    assert select_suite(ROOT, "dev").split == "dev"
    assert select_suite(ROOT, "heldout", final_report=True).split == "heldout"


def test_duplicate_ids_fail():
    data = load_suite(ROOT / "cases/poker/dev.yaml").model_dump()
    data["cases"].append(data["cases"][0])
    with pytest.raises(ValidationError, match="duplicate"):
        Suite.model_validate(data)


@pytest.mark.parametrize(
    "data",
    [
        {"action": "call", "rubric": "needs a call"},
        {
            "action": "clarify",
            "rubric": "missing identity",
            "acceptable": [{"tool": "foo", "arguments": {}}],
        },
        {"action": "no_call", "rubric": "", "acceptable": []},
    ],
)
def test_invalid_expectations_fail(data):
    with pytest.raises(ValidationError):
        Expected.model_validate(data)


def test_conflicting_argument_constraints_fail():
    with pytest.raises(ValidationError):
        Call(tool="compute_stats", arguments={"player_hash": "x"}, absent_or_null=["player_hash"])


def test_export_does_not_leak_labels_or_rubric_into_query():
    case = select_suite(ROOT, "dev").cases[0]
    exported = payload(case, "http://localhost:8766/mcp")
    assert exported["query"] == f"Context: {case.context}\n\nRequest: {case.request}"
    assert case.reason not in exported["query"]
    assert case.expected.rubric not in exported["query"]
    assert exported["expected_tool_calls"][0]["parameters"] == {"limit": 5}
    assert any("absent-or-null" in warning for warning in adapter_limits(case))


def test_clarify_export_is_explicitly_lossy():
    case = next(c for c in select_suite(ROOT, "dev").cases if c.expected.action == "clarify")
    assert payload(case, "http://localhost/mcp")["expected_tool_calls"] == []
    assert any("clarification" in warning for warning in adapter_limits(case))


def test_schema_validation_rejects_unknown_tools():
    with pytest.raises(ValueError, match="unknown tool"):
        validate_cases([select_suite(ROOT, "dev")], [])


def test_description_diff_rejects_other_mutations():
    a = [{"name": "x", "description": "before", "inputSchema": {"type": "object"}}]
    b = [{**a[0], "description": "after"}]
    verify_description_only(a, b, "x")
    with pytest.raises(ValueError):
        verify_description_only(a, a, "x")
    b[0]["inputSchema"] = {"type": "string"}
    with pytest.raises(ValueError, match="more than"):
        verify_description_only(a, b, "x")
