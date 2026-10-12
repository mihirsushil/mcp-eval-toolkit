"""Offline scoring of immutable run evidence and paired A/B summaries."""

import json
from pathlib import Path
from statistics import mean
from typing import Literal
from uuid import UUID

from pydantic import Field

from .cases import StrictModel, Suite
from .evidence import canonical_hash, digest, write_json
from .scoring import score
from .statistics import paired_summary


class Review(StrictModel):
    key: str
    trace_sha256: str
    case_sha256: str
    decision: Literal["pass", "fail"]
    reviewer: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


def read_json(path: Path):
    return json.loads(path.read_text())


def safe_run_id(value: str) -> str:
    if str(UUID(value)) != value:
        raise ValueError("upstream run ID must be a canonical UUID")
    return value


def escaped(value) -> str:
    return (
        str(value).replace("&", "&amp;").replace("<", "&lt;").replace("|", "\\|").replace("\n", " ")
    )


def report(directory: Path, reviews_path: Path | None = None, draws=5000, seed=0) -> dict:
    if reviews_path and reviews_path.resolve().parent == (directory / "scored").resolve():
        raise ValueError("save completed reviews outside the generated scored/ directory")
    manifest = read_json(directory / "manifest.json")
    if manifest.get("kind") not in {"scripted-demo", "mcp-tef-live-baseline"}:
        raise ValueError("report requires baseline/demo evidence, not an infrastructure preflight")
    scripted = manifest["kind"] == "scripted-demo"
    suite_data = read_json(directory / "suite.json")
    if canonical_hash(suite_data) != manifest.get("evaluation_suite_sha256"):
        raise ValueError("frozen evaluation suite checksum mismatch")
    suite = Suite.model_validate(suite_data)
    repeats = manifest.get("repeats")
    if type(repeats) is not int or repeats < 1:
        raise ValueError("manifest needs a positive integer repeat count")
    snapshots = {variant: read_json(directory / f"tools-{variant}.json") for variant in ("A", "B")}
    for variant, tools in snapshots.items():
        if canonical_hash(tools) != manifest.get("tool_sha256", {}).get(variant):
            raise ValueError(f"tool snapshot {variant} checksum mismatch")
    reviews = {}
    if reviews_path:
        for data in read_json(reviews_path):
            review = Review.model_validate(data)
            if review.key in reviews:
                raise ValueError(f"duplicate review: {review.key}")
            reviews[review.key] = review
    records = {}
    for path in sorted((directory / "runs").glob("*.json")):
        record = read_json(path)
        case_id, repeat, variant = record["case_id"], record["repeat"], record["variant"]
        if case_id not in {case.id for case in suite.cases} or variant not in {"A", "B"}:
            raise ValueError(f"unexpected run identity in {path.name}")
        if type(repeat) is not int or not 0 <= repeat < repeats:
            raise ValueError(f"invalid repeat in {path.name}")
        key = f"{case_id}:{repeat}:{variant}"
        if key in records:
            raise ValueError(f"duplicate run: {key}")
        records[key] = (record, path)
    verdicts, queue, seen_reviews = [], [], set()
    for case in suite.cases:
        for repeat in range(repeats):
            for variant in ("A", "B"):
                key = f"{case.id}:{repeat}:{variant}"
                entry = records.get(key)
                trace = None
                raw = None
                if entry:
                    record, path = entry
                    result = record["result"]
                    raw = str(path.relative_to(directory))
                    if result.get("id"):
                        trace_path = directory / "traces" / f"{safe_run_id(result['id'])}.json"
                        if trace_path.exists():
                            trace = read_json(trace_path)
                    if trace is not None and canonical_hash(trace) != record.get("trace_sha256"):
                        raise ValueError(f"trace checksum mismatch: {key}")
                    if trace is not None:
                        queries = [
                            part.get("content")
                            for message in trace.get("messages", [])
                            for part in message.get("parts", [])
                            if part.get("part_kind") == "user-prompt"
                        ]
                        if queries != [case.query()]:
                            raise ValueError(f"trace query does not match frozen case: {key}")
                    requested = manifest["requested_model_settings"]
                    if result.get("status") == "completed" and any(
                        (result.get("model_settings") or {}).get(field) != requested[field]
                        for field in ("provider", "model")
                    ):
                        raise ValueError(f"recorded model/provider differs from manifest: {key}")
                else:
                    result = {"status": "missing"}
                verdict = score(case, result, trace, snapshots[variant], scripted=scripted)
                verdict.update(key=key, repeat=repeat, variant=variant, raw=raw)
                trace_hash = canonical_hash(trace) if trace is not None else "missing"
                case_hash = canonical_hash(case.model_dump())
                verdict["final_pass"] = verdict["deterministic_pass"]
                review = reviews.get(key)
                if review:
                    if not verdict["review_required"] or verdict["status"] != "scored":
                        raise ValueError(f"review does not apply to this result: {key}")
                    if review.trace_sha256 != trace_hash or review.case_sha256 != case_hash:
                        raise ValueError(f"stale review hashes: {key}")
                    seen_reviews.add(key)
                    verdict["review"] = review.model_dump()
                    verdict["final_pass"] = (
                        verdict["deterministic_pass"] and review.decision == "pass"
                    )
                elif verdict["review_required"] and verdict["deterministic_pass"] is True:
                    verdict["final_pass"] = None
                    queue.append(
                        {
                            "key": key,
                            "trace_sha256": trace_hash,
                            "case_sha256": case_hash,
                            "decision": None,
                            "reviewer": "",
                            "rationale": "",
                            "request": case.query(),
                            "rubric": case.expected.rubric,
                            "response_text": verdict["text"],
                            "raw": raw,
                        }
                    )
                verdicts.append(verdict)
    if set(reviews) != seen_reviews:
        raise ValueError(
            f"reviews reference unknown results: {sorted(set(reviews) - seen_reviews)}"
        )
    pairs, changes = [], []
    for case in suite.cases:
        rows = [row for row in verdicts if row["case_id"] == case.id]
        if any(row["status"] != "scored" for row in rows):
            changes.append({"case_id": case.id, "change": "incomplete", "delta": None})
            continue
        a = [row["deterministic_pass"] for row in rows if row["variant"] == "A"]
        b = [row["deterministic_pass"] for row in rows if row["variant"] == "B"]
        pairs.append((a, b))
        delta = mean(b) - mean(a)
        changes.append(
            {
                "case_id": case.id,
                "change": "improved" if delta > 0 else "regressed" if delta < 0 else "unchanged",
                "delta": delta,
            }
        )
    summary = {
        "scoring_source_sha256": {
            name: digest((Path(__file__).parent / name).read_bytes())
            for name in ("scoring.py", "statistics.py", "reporting.py")
        },
        "reviews_sha256": digest(reviews_path.read_bytes()) if reviews_path else None,
        "kind": manifest["kind"],
        "metric": "deterministic tool behavior (answer quality excluded)",
        "expected_cases": len(suite.cases),
        "repeats": repeats,
        "expected_attempts": len(verdicts),
        "scored_attempts": sum(row["status"] == "scored" for row in verdicts),
        "error_or_missing_attempts": sum(row["status"] != "scored" for row in verdicts),
        "pending_reviews": len(queue),
        "reviewed_responses": len(seen_reviews),
        "review_failures": sum(review.decision == "fail" for review in reviews.values()),
        "changes": changes,
        "paired": paired_summary(pairs, draws=draws, seed=seed) if pairs else None,
        "complete": all(row["status"] == "scored" for row in verdicts),
    }
    output = directory / "scored"
    write_json(output / "summary.json", summary)
    write_json(output / "scores.json", verdicts)
    write_json(output / "review-queue.json", queue)
    write_json(
        output / "review-template.json",
        [
            {
                key: row[key]
                for key in (
                    "key",
                    "trace_sha256",
                    "case_sha256",
                    "decision",
                    "reviewer",
                    "rationale",
                )
            }
            for row in queue
        ],
    )
    title = "SCRIPTED DEMO — not model performance" if scripted else "MCP A/B behavioral report"
    lines = [
        f"# {title}",
        "",
        f"Metric: {summary['metric']}.",
        "",
        f"Coverage: {summary['scored_attempts']}/{summary['expected_attempts']} attempts scored; "
        f"{summary['error_or_missing_attempts']} missing/errors. {len(suite.cases)} cases, {repeats} repeats per variant.",
        "",
        f"Human review pending for {len(queue)} responses; {len(seen_reviews)} reviews applied, {summary['review_failures']} failed. No-call correctness does not establish answer/clarification quality.",
        "",
    ]
    if not summary["complete"]:
        lines += [
            "INCOMPLETE: summary uses only cases with every A/B repeat scored; exclusions can bias it. No full-suite conclusion.",
            "",
        ]
    stats = summary["paired"]
    if stats:
        lines += [
            f"Paired comparison: {stats['cases']} complete cases; {stats['attempts_per_variant']} attempts per variant.",
            "",
        ]
        for variant in ("a", "b"):
            interval = stats[f"{variant}_interval"]
            interval_text = (
                f"95% interval [{interval[0]:.1%}, {interval[1]:.1%}]"
                if interval
                else "interval unavailable (fewer than two cases)"
            )
            lines.append(f"- {variant.upper()}: {stats[f'{variant}_rate']:.1%}; {interval_text}.")
        delta_interval = stats["delta_interval"]
        lines += [""]
        if delta_interval:
            lines += [
                f"B − A: {stats['delta'] * 100:+.1f} percentage points; 95% interval [{delta_interval[0] * 100:+.1f}, {delta_interval[1] * 100:+.1f}]."
            ]
        else:
            lines += [
                f"B − A: {stats['delta'] * 100:+.1f} percentage points; interval unavailable."
            ]
        lines += [
            "",
            stats["method"] + f" ({draws} draws, seed {seed}).",
            "",
            stats["limitation"],
            "",
        ]
    lines += ["## Case changes", "", "| Case | Change | Difference |", "|---|---|---:|"]
    for row in changes:
        delta = "—" if row["delta"] is None else f"{row['delta'] * 100:+.1f} pp"
        lines.append(f"| {row['case_id']} | {row['change']} | {delta} |")
    lines += [
        "",
        "## Raw evidence",
        "",
        "| Case | Repeat | Variant | Call checks | Case verdict | Reason | Evidence |",
        "|---|---:|---|---|---|---|---|",
    ]
    for row in verdicts:
        check = (
            "error"
            if row["status"] != "scored"
            else "pass"
            if row["deterministic_pass"]
            else "fail"
        )
        link = f"[raw](../{row['raw']})" if row["raw"] else "missing"
        reason = "; ".join(row["reasons"]) or (
            "rubric review pending" if row["final_pass"] is None else "deterministic checks passed"
        )
        if row.get("review"):
            reason += "; review: " + row["review"]["rationale"]
        final = (
            "error"
            if row["status"] != "scored"
            else "pending"
            if row["final_pass"] is None
            else "pass"
            if row["final_pass"]
            else "fail"
        )
        lines.append(
            f"| {row['case_id']} | {row['repeat']} | {row['variant']} | {check} | {final} | {escaped(reason)} | {link} |"
        )
    lines += [
        "",
        "Review inputs and verdicts are in `review-queue.json` and `scores.json`. Rates above exclude answer quality.",
        "",
    ]
    (output / "report.md").write_text("\n".join(lines))
    return summary
