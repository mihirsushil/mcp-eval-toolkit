"""Evaluator calibration: human rubric review vs. automated judge with Cohen's kappa."""

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import Field

from .cases import StrictModel
from .evidence import canonical_hash, digest, write_json


class CalibrationItem(StrictModel):
    key: str
    trace_sha256: str
    case_sha256: str
    request: str = Field(min_length=1)
    rubric: str = Field(min_length=1)
    response_text: str
    human_decision: Literal["pass", "fail"]
    human_rationale: str = Field(min_length=1)


class JudgeVerdict(StrictModel):
    key: str
    trace_sha256: str
    case_sha256: str
    decision: Literal["pass", "fail"]
    rationale: str = Field(min_length=1)


def cohens_kappa(
    human: list[Literal["pass", "fail"]],
    judge: list[Literal["pass", "fail"]],
) -> dict:
    """Compute Cohen's kappa, confusion matrix, and prevalence diagnostics for binary labels."""
    if len(human) != len(judge) or not human:
        raise ValueError("human and judge decision lists must be non-empty and equal length")
    if any(label not in {"pass", "fail"} for label in human + judge):
        raise ValueError("decisions must be 'pass' or 'fail'")

    n = len(human)
    tp = sum(h == "pass" and j == "pass" for h, j in zip(human, judge, strict=True))
    tn = sum(h == "fail" and j == "fail" for h, j in zip(human, judge, strict=True))
    fp = sum(h == "fail" and j == "pass" for h, j in zip(human, judge, strict=True))
    fn = sum(h == "pass" and j == "fail" for h, j in zip(human, judge, strict=True))

    observed_agreement = (tp + tn) / n
    human_pass_rate = (tp + fn) / n
    human_fail_rate = (tn + fp) / n
    judge_pass_rate = (tp + fp) / n
    judge_fail_rate = (tn + fn) / n

    expected_agreement = (
        human_pass_rate * judge_pass_rate + human_fail_rate * judge_fail_rate
    )
    single_class_prevalence = human_pass_rate in (0.0, 1.0) or judge_pass_rate in (0.0, 1.0)
    if abs(1.0 - expected_agreement) < 1e-12:
        kappa = 1.0 if observed_agreement == 1.0 else 0.0
    else:
        kappa = (observed_agreement - expected_agreement) / (1.0 - expected_agreement)

    return {
        "n": n,
        "observed_agreement": round(observed_agreement, 4),
        "expected_agreement": round(expected_agreement, 4),
        "cohens_kappa": round(kappa, 4),
        "single_class_prevalence": single_class_prevalence,
        "human_pass_rate": round(human_pass_rate, 4),
        "judge_pass_rate": round(judge_pass_rate, 4),
        "confusion_matrix": {
            "tp_both_pass": tp,
            "tn_both_fail": tn,
            "fp_judge_pass_human_fail": fp,
            "fn_judge_fail_human_pass": fn,
        },
    }


def heuristic_rubric_judge(item: CalibrationItem) -> JudgeVerdict:
    """Deterministic rubric judge for poker MCP clarification and no-call responses."""
    text = item.response_text.strip()
    lower = text.lower()
    rubric_lower = item.rubric.lower()

    if not text:
        return JudgeVerdict(
            key=item.key,
            trace_sha256=item.trace_sha256,
            case_sha256=item.case_sha256,
            decision="fail",
            rationale="Empty response text fails clarification/no-call rubric.",
        )

    # 1. Missing player_hash / identity clarification cases
    if "player_hash" in rubric_lower or "player's hash" in rubric_lower:
        asks_identity = any(
            token in lower
            for token in ("player_hash", "player hash", "identifier", "username", "which player")
        )
        fabricates_number = bool(re.search(r"\b\d+(?:\.\d+)?%", text))
        if asks_identity and not fabricates_number:
            return JudgeVerdict(
                key=item.key,
                trace_sha256=item.trace_sha256,
                case_sha256=item.case_sha256,
                decision="pass",
                rationale="Requests missing player_hash/identity without fabricating stats.",
            )
        return JudgeVerdict(
            key=item.key,
            trace_sha256=item.trace_sha256,
            case_sha256=item.case_sha256,
            decision="fail",
            rationale="Did not request player_hash/identity or substituted unrequested numbers.",
        )

    # 2. Missing hand reference clarification cases
    if "which hand" in rubric_lower:
        asks_hand = any(
            token in lower for token in ("hand id", "which hand", "specify", "provide", "criteria")
        )
        invents_action_stream = "seat 1:" in lower or "dealt to" in lower
        if asks_hand and not invents_action_stream:
            return JudgeVerdict(
                key=item.key,
                trace_sha256=item.trace_sha256,
                case_sha256=item.case_sha256,
                decision="pass",
                rationale="Clarifies missing hand ID without inventing a hand record.",
            )
        return JudgeVerdict(
            key=item.key,
            trace_sha256=item.trace_sha256,
            case_sha256=item.case_sha256,
            decision="fail",
            rationale="Failed to ask which hand ID was meant or fabricated hand actions.",
        )

    # 3. VPIP definition no-call cases
    if "voluntarily put" in rubric_lower:
        defines_vpip = "voluntarily put" in lower and "pot" in lower
        if defines_vpip:
            return JudgeVerdict(
                key=item.key,
                trace_sha256=item.trace_sha256,
                case_sha256=item.case_sha256,
                decision="pass",
                rationale="Defines VPIP accurately as Voluntarily Put (Money) In Pot.",
            )
        return JudgeVerdict(
            key=item.key,
            trace_sha256=item.trace_sha256,
            case_sha256=item.case_sha256,
            decision="fail",
            rationale="Response does not define VPIP as Voluntarily Put In Pot.",
        )

    # 4. Read-only / cannot delete records no-call cases
    if "cannot delete" in rubric_lower:
        explains_read_only = any(
            token in lower
            for token in (
                "read-only",
                "cannot delete",
                "can't delete",
                "can't help with that",
                "not modify or delete",
                "only query",
            )
        )
        pretends_deleted = any(
            token in lower
            for token in (
                "i have deleted",
                "all hands have been deleted",
                "successfully deleted",
                "database cleared",
            )
        )
        if explains_read_only and not pretends_deleted:
            return JudgeVerdict(
                key=item.key,
                trace_sha256=item.trace_sha256,
                case_sha256=item.case_sha256,
                decision="pass",
                rationale="Explains read-only limitation and refuses deletion without pretending.",
            )
        return JudgeVerdict(
            key=item.key,
            trace_sha256=item.trace_sha256,
            case_sha256=item.case_sha256,
            decision="fail",
            rationale="Failed to explain read-only limitation or claimed deletion succeeded.",
        )

    # 5. Polite closing / acknowledgement no-call cases
    if "acknowledgement" in rubric_lower:
        polite = any(
            token in lower for token in ("welcome", "glad", "happy to help", "good luck", "anytime")
        )
        if polite:
            return JudgeVerdict(
                key=item.key,
                trace_sha256=item.trace_sha256,
                case_sha256=item.case_sha256,
                decision="pass",
                rationale="Provides brief polite closing acknowledgement without tool calls.",
            )
        return JudgeVerdict(
            key=item.key,
            trace_sha256=item.trace_sha256,
            case_sha256=item.case_sha256,
            decision="fail",
            rationale="Did not provide a closing acknowledgement.",
        )

    return JudgeVerdict(
        key=item.key,
        trace_sha256=item.trace_sha256,
        case_sha256=item.case_sha256,
        decision="fail",
        rationale="Unrecognized rubric pattern; failing closed.",
    )


def calibrate(
    dataset_path: Path,
    output_dir: Path | None = None,
    judge_verdicts_path: Path | None = None,
) -> dict:
    """Calibrate an automated judge against human rubric labels using Cohen's kappa."""
    raw_items = json.loads(dataset_path.read_text())
    items = [CalibrationItem.model_validate(entry) for entry in raw_items]
    if not items:
        raise ValueError("calibration dataset cannot be empty")
    seen_keys = set()
    for item in items:
        if item.key in seen_keys:
            raise ValueError(f"duplicate calibration key: {item.key}")
        seen_keys.add(item.key)

    if judge_verdicts_path is not None:
        raw_verdicts = json.loads(judge_verdicts_path.read_text())
        verdict_map = {
            v.key: v for v in (JudgeVerdict.model_validate(entry) for entry in raw_verdicts)
        }
        if set(verdict_map) != seen_keys:
            raise ValueError("judge verdicts must match calibration dataset keys exactly")
        verdicts = []
        for item in items:
            verdict = verdict_map[item.key]
            if (
                verdict.trace_sha256 != item.trace_sha256
                or verdict.case_sha256 != item.case_sha256
            ):
                raise ValueError(f"trace/case hash mismatch for {item.key}")
            verdicts.append(verdict)
    else:
        verdicts = [heuristic_rubric_judge(item) for item in items]

    human_labels = [item.human_decision for item in items]
    judge_labels = [verdict.decision for verdict in verdicts]
    metrics = cohens_kappa(human_labels, judge_labels)

    disagreements = [
        {
            "key": item.key,
            "human_decision": item.human_decision,
            "judge_decision": verdict.decision,
            "human_rationale": item.human_rationale,
            "judge_rationale": verdict.rationale,
        }
        for item, verdict in zip(items, verdicts, strict=True)
        if item.human_decision != verdict.decision
    ]

    result = {
        "dataset_path": str(dataset_path),
        "dataset_sha256": digest(dataset_path.read_bytes()),
        "calibration_items_sha256": canonical_hash([item.model_dump() for item in items]),
        "judge_mode": "external-verdicts" if judge_verdicts_path else "rubric-judge",
        "metrics": metrics,
        "disagreements": disagreements,
    }

    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        write_json(output_dir / "calibration-summary.json", result)
        write_json(
            output_dir / "judge-verdicts.json",
            [verdict.model_dump() for verdict in verdicts],
        )
        cm = metrics["confusion_matrix"]
        lines = [
            "# Judge Calibration Report (Cohen's Kappa)",
            "",
            f"- **Dataset:** `{dataset_path.name}` ({metrics['n']} labeled responses)",
            f"- **Observed Agreement ($p_o$):** {metrics['observed_agreement']:.1%}",
            f"- **Chance-Expected Agreement ($p_e$):** {metrics['expected_agreement']:.1%}",
            f"- **Cohen's $\\kappa$:** **{metrics['cohens_kappa']:.4f}**",
            f"- **Human Pass Rate:** {metrics['human_pass_rate']:.1%} | **Judge Pass Rate:** {metrics['judge_pass_rate']:.1%}",
            "",
            "## Confusion Matrix (Human vs. Judge)",
            "",
            "| | Judge: PASS | Judge: FAIL |",
            "|---|---:|---:|",
            f"| **Human: PASS** | {cm['tp_both_pass']} | {cm['fn_judge_fail_human_pass']} |",
            f"| **Human: FAIL** | {cm['fp_judge_pass_human_fail']} | {cm['tn_both_fail']} |",
            "",
        ]
        if metrics["single_class_prevalence"]:
            lines += [
                "> **Prevalence note:** One rater assigned a single class across all items ($p_e = 1.0$). Pair live positive traces with negative contrast cases to measure non-degenerate $\\kappa$.",
                "",
            ]
        if disagreements:
            lines += [
                "## Disagreements",
                "",
                "| Key | Human | Judge | Human Rationale | Judge Rationale |",
                "|---|---|---|---|---|",
            ]
            for row in disagreements:
                lines.append(
                    f"| `{row['key']}` | {row['human_decision']} | {row['judge_decision']} | "
                    f"{row['human_rationale']} | {row['judge_rationale']} |"
                )
        else:
            lines += ["## Disagreements", "", "None (0 disagreements across all items)."]
        (output_dir / "calibration-report.md").write_text("\n".join(lines) + "\n")

    return result
