import json
from pathlib import Path

import pytest

from mcp_eval_toolkit.calibration import CalibrationItem, calibrate, cohens_kappa

ROOT = Path(__file__).resolve().parents[1]


def test_cohens_kappa_computes_exact_chance_corrected_agreement():
    # 10 items: 4 TP, 4 TN, 1 FP, 1 FN -> p_o = 0.8, p_e = 0.5*0.5 + 0.5*0.5 = 0.5 -> kappa = 0.6
    human = ["pass", "pass", "pass", "pass", "pass", "fail", "fail", "fail", "fail", "fail"]
    judge = ["pass", "pass", "pass", "pass", "fail", "pass", "fail", "fail", "fail", "fail"]
    metrics = cohens_kappa(human, judge)
    assert metrics["n"] == 10
    assert metrics["observed_agreement"] == 0.8
    assert metrics["expected_agreement"] == 0.5
    assert metrics["cohens_kappa"] == 0.6
    assert metrics["single_class_prevalence"] is False
    assert metrics["confusion_matrix"] == {
        "tp_both_pass": 4,
        "tn_both_fail": 4,
        "fp_judge_pass_human_fail": 1,
        "fn_judge_fail_human_pass": 1,
    }


def test_cohens_kappa_flags_single_class_prevalence():
    human = ["pass", "pass", "pass", "pass"]
    judge = ["pass", "pass", "pass", "pass"]
    metrics = cohens_kappa(human, judge)
    assert metrics["observed_agreement"] == 1.0
    assert metrics["expected_agreement"] == 1.0
    assert metrics["cohens_kappa"] == 1.0
    assert metrics["single_class_prevalence"] is True


def test_calibrate_on_poker_judge_calibration_dataset(tmp_path):
    dataset = ROOT / "cases" / "poker" / "judge_calibration.json"
    summary = calibrate(dataset, output_dir=tmp_path)
    assert summary["metrics"]["n"] == 24
    assert summary["metrics"]["human_pass_rate"] == 0.5
    assert summary["metrics"]["judge_pass_rate"] == 0.5
    assert summary["metrics"]["cohens_kappa"] == 1.0
    assert summary["disagreements"] == []
    assert (tmp_path / "calibration-report.md").is_file()
    assert (tmp_path / "calibration-summary.json").is_file()
    assert (tmp_path / "judge-verdicts.json").is_file()


def test_calibrate_rejects_stale_trace_hash_in_external_verdicts(tmp_path):
    item = CalibrationItem(
        key="clarify_player_stats:0:A",
        trace_sha256="a" * 64,
        case_sha256="b" * 64,
        request="What is my VPIP?",
        rubric="Ask for the player's hash or identity mapping; do not substitute population statistics or guess a hash.",
        response_text="Please provide your player_hash.",
        human_decision="pass",
        human_rationale="Asks for player_hash.",
    )
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(json.dumps([item.model_dump()]))
    verdicts_path = tmp_path / "verdicts.json"
    verdicts_path.write_text(
        json.dumps(
            [
                {
                    "key": "clarify_player_stats:0:A",
                    "trace_sha256": "c" * 64,
                    "case_sha256": "b" * 64,
                    "decision": "pass",
                    "rationale": "Stale hash",
                }
            ]
        )
    )
    with pytest.raises(ValueError, match="hash mismatch"):
        calibrate(dataset_path, judge_verdicts_path=verdicts_path)
