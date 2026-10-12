from copy import deepcopy
from pathlib import Path

import pytest

from mcp_eval_toolkit.cases import load_suite
from mcp_eval_toolkit.scoring import score
from mcp_eval_toolkit.statistics import paired_summary

ROOT = Path(__file__).resolve().parents[1]
CASES = {case.id: case for case in load_suite(ROOT / "cases/poker/dev.yaml").cases}
RUN_ID = "a36aff42-d965-4a7d-81ae-89024c1014d5"
RESULT = {"id": RUN_ID, "status": "completed"}
TOOLS = [
    {
        "name": "compute_stats",
        "inputSchema": {
            "type": "object",
            "properties": {
                name: {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None}
                for name in ("player_hash", "position", "start_date", "end_date")
            },
        },
    }
]


def trace(calls=(), text="", scripted=True):
    messages = [{"kind": "request", "parts": [{"part_kind": "user-prompt", "content": "fixture"}]}]
    for index, (name, args) in enumerate(calls):
        messages += [
            {
                "kind": "response",
                "parts": [
                    {
                        "part_kind": "tool-call",
                        "tool_name": name,
                        "args": args,
                        "tool_call_id": f"c{index}",
                    }
                ],
            },
            {
                "kind": "request",
                "parts": [
                    {
                        "part_kind": "tool-return",
                        "tool_name": name,
                        "tool_call_id": f"c{index}",
                        "content": {"value": "fixture"},
                    }
                ],
            },
        ]
    messages += [
        {
            "kind": "response",
            "parts": [
                {"part_kind": "text", "content": text},
                {
                    "part_kind": "tool-call",
                    "tool_name": "final_result",
                    "args": {"confidence": "high"},
                    "tool_call_id": "final",
                },
            ],
        },
        {
            "kind": "request",
            "parts": [
                {
                    "part_kind": "tool-return",
                    "tool_name": "final_result",
                    "tool_call_id": "final",
                    "content": "Final result processed.",
                }
            ],
        },
    ]
    return {
        "version": 1,
        "kind": "scripted" if scripted else "live",
        "upstream_run_id": RUN_ID,
        "messages": messages,
    }


def grade(case_id, calls=(), evidence=None):
    return score(
        CASES[case_id],
        RESULT,
        evidence if evidence is not None else trace(calls),
        TOOLS,
        scripted=True,
    )


def test_empty_arguments_are_valid_but_missing_trace_is_not():
    assert grade("stats_population", [("compute_stats", {})])["deterministic_pass"] is True
    missing = score(CASES["stats_population"], RESULT, None, TOOLS, scripted=True)
    assert missing["status"] == "error" and missing["deterministic_pass"] is None


def test_upstream_full_credit_filter_is_rejected():
    result = grade("stats_population", [("compute_stats", {"player_hash": "invented"})])
    assert result["deterministic_pass"] is False
    assert "player_hash" in str(result["reasons"])


def test_valid_null_defaults_do_not_lose_points():
    assert (
        grade("stats_population", [("compute_stats", {"player_hash": None})])["deterministic_pass"]
        is True
    )


@pytest.mark.parametrize(
    "arguments",
    [
        {"player_hash": "376d6fd36aec498b", "position": "BB"},
        {"position": "SB"},
        {"player_hash": "376d6fd36aec498b", "position": "SB", "start_date": "invented"},
        {"player_hash": "376d6fd36aec498b", "position": "SB", "unknown": None},
        {"player_hash": "376d6fd36aec498b", "position": True},
    ],
)
def test_wrong_missing_extra_or_invalid_arguments_fail(arguments):
    assert (
        grade("stats_player_position", [("compute_stats", arguments)])["deterministic_pass"]
        is False
    )


def test_duplicate_and_wrong_tools_fail():
    assert (
        grade("stats_population", [("compute_stats", {}), ("compute_stats", {})])[
            "deterministic_pass"
        ]
        is False
    )
    assert grade("stats_population", [("query_hands", {})])["deterministic_pass"] is False


def test_observed_malformed_arguments_are_model_failures_not_missing_evidence():
    verdict = grade("stats_population", [("compute_stats", "not-json")])
    assert verdict["status"] == "scored"
    assert verdict["deterministic_pass"] is False


def test_clarification_needs_review_even_with_no_calls():
    result = grade("clarify_player_stats", evidence=trace(text="What is your player hash?"))
    assert result["deterministic_pass"] is True
    assert result["review_required"] is True
    assert result["text"] == "What is your player hash?"
    assert grade("clarify_player_stats", [("compute_stats", {})])["deterministic_pass"] is False


def test_failed_run_is_not_a_model_failure_score():
    result = score(CASES["stats_population"], {"status": "failed"}, None, TOOLS)
    assert result["status"] == "error" and result["deterministic_pass"] is None


@pytest.mark.parametrize(
    "mutation", ["missing_return", "missing_args", "wrong_id", "live_mismatch", "unknown_part"]
)
def test_incomplete_or_mismatched_evidence_fails_closed(mutation):
    evidence = trace([("compute_stats", {})])
    if mutation == "missing_return":
        evidence["messages"].pop(2)
    elif mutation == "missing_args":
        del evidence["messages"][1]["parts"][0]["args"]
    elif mutation == "wrong_id":
        evidence["upstream_run_id"] = "wrong"
    elif mutation == "live_mismatch":
        evidence["kind"] = "live"
    else:
        evidence["messages"][1]["parts"].append({"part_kind": "unrecognized-action"})
    result = grade("stats_population", evidence=evidence)
    assert result["status"] == "error" and result["deterministic_pass"] is None


def test_alternative_expected_call_is_accepted():
    case = deepcopy(CASES["stats_player_position"])
    alternative = deepcopy(case.expected.acceptable[0])
    alternative.arguments["position"] = "BB"
    case.expected.acceptable.append(alternative)
    result = score(
        case, RESULT, trace([("compute_stats", alternative.arguments)]), TOOLS, scripted=True
    )
    assert result["deterministic_pass"] is True


def test_bootstrap_is_paired_reproducible_and_clusters_repeats():
    pairs = [
        ([False, False], [True, True]),
        ([True, True], [False, False]),
        ([True, True], [True, True]),
    ]
    one = paired_summary(pairs, draws=200, seed=3)
    doubled = paired_summary([(a * 2, b * 2) for a, b in pairs], draws=200, seed=3)
    assert one["delta"] == 0
    assert one["a_rate"] == one["b_rate"] == 2 / 3
    assert one["delta_interval"] == doubled["delta_interval"]
    assert one == paired_summary(pairs, draws=200, seed=3)
    assert one["delta_interval"][0] <= 0 <= one["delta_interval"][1]


def test_single_case_does_not_claim_an_interval():
    assert paired_summary([([False], [True])], draws=100)["delta_interval"] is None
    with pytest.raises(ValueError):
        paired_summary([([True], [])])
