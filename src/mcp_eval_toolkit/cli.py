"""CLI for Phase 0; no framework decision is implied by the adapter."""

import argparse
import asyncio
import json
import os
from pathlib import Path

from .cases import load_suite, select_suite
from .evidence import canonical_hash, create_artifacts, write_json
from .reporting import report, safe_run_id
from .runtime import environment, preflight, validate_cases
from .tef import SYSTEM_PROMPT, adapter_limits, create_case, execute


async def baseline(args, root: Path, output: Path):
    suite = select_suite(root, args.split, args.final_report)
    scripted = args.command == "demo"
    if scripted:
        demo_ids = {
            "stats_population",
            "stats_player_position",
            "clarify_player_stats",
            "no_call_vpip_definition",
        }
        suite = suite.model_copy(
            update={"cases": [case for case in suite.cases if case.id in demo_ids]}
        )
    key_name = {
        "openrouter": "OPENROUTER_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "ollama": "",
    }[args.provider]
    api_key = os.environ.get(key_name) if key_name and not scripted else None
    if key_name and not api_key and not scripted:
        raise ValueError(f"set {key_name} in the process environment; do not paste it into a case")
    settings = {
        "provider": args.provider,
        "model": args.model,
        "temperature": args.temperature,
        "timeout": 60,
        "max_retries": 0,
        "system_prompt": SYSTEM_PROMPT,
    }
    if args.base_url:
        settings["base_url"] = args.base_url
    async with environment(root, args.poker_repo, args.tef_repo, output, scripted=scripted) as (
        client,
        urls,
        snapshots,
        manifest,
    ):
        validate_cases([suite], snapshots["A"])
        manifest.update(
            {
                "kind": "scripted-demo" if scripted else "mcp-tef-live-baseline",
                "split": args.split,
                "repeats": args.repeats,
                "requested_model_settings": settings,
                "effective_settings_caveat": "Pinned upstream persists temperature, timeout and max_retries but does not forward them to Agent; provider defaults apply. No matched random seeds.",
                "run_order": "alternate AB/BA per case and repeat; no provider seed pairing",
                "status": "running",
                "evaluation_suite_sha256": canonical_hash(suite.model_dump()),
            }
        )
        write_json(output / "suite.json", suite.model_dump())
        write_json(output / "manifest.json", manifest)
        completed = []
        try:
            created = {}
            for variant, url in urls.items():
                for case in suite.cases:
                    result = await create_case(client, case, url)
                    created[variant, case.id] = result["id"]
                    write_json(output / "upstream-cases" / f"{variant}-{case.id}.json", result)
            for repeat in range(args.repeats):
                for index, case in enumerate(suite.cases):
                    order = ("A", "B") if (index + repeat) % 2 == 0 else ("B", "A")
                    for variant in order:
                        record = {
                            "case_id": case.id,
                            "variant": variant,
                            "repeat": repeat,
                            "adapter_limits": adapter_limits(case),
                            "result": await execute(
                                client, created[variant, case.id], settings, api_key
                            ),
                        }
                        run_id = safe_run_id(record["result"]["id"])
                        trace_path = output / "traces" / f"{run_id}.json"
                        record["trace_sha256"] = (
                            canonical_hash(json.loads(trace_path.read_text()))
                            if trace_path.exists()
                            else None
                        )
                        write_json(output / "runs" / f"{case.id}-{repeat}-{variant}.json", record)
                        completed.append(record)
                        manifest["upstream_runs_returned"] = len(completed)
                        manifest["scripted_model_runs" if scripted else "live_model_runs"] = sum(
                            item["result"]["status"] == "completed" for item in completed
                        )
                        write_json(output / "manifest.json", manifest)
                        print(
                            f"{case.id} {variant} repeat={repeat}: {record['result']['status']}",
                            flush=True,
                        )
                        if record["result"]["status"] == "failed":
                            raise RuntimeError(
                                "upstream run failed; retained raw result and stopped"
                            )
            manifest["status"] = "completed_pending_manual_rubric_review"
        except BaseException:
            manifest["status"] = "incomplete"
            raise
        finally:
            write_json(output / "manifest.json", manifest)
            rows = [
                "# SCRIPTED DEMO — not model performance" if scripted else "# mcp-tef raw baseline",
                "",
                "These are upstream classifications, not rubric pass rates.",
                "",
                "| Case | Repeat | Variant | Status | Classification | Raw result |",
                "|---|---:|---|---|---|---|",
            ]
            for record in completed:
                result = record["result"]
                name = f"{record['case_id']}-{record['repeat']}-{record['variant']}.json"
                rows.append(
                    f"| {record['case_id']} | {record['repeat']} | {record['variant']} | {result['status']} | {result.get('classification')} | [JSON](runs/{name}) |"
                )
            (output / "report.md").write_text("\n".join(rows) + "\n")
            report(output)
    return {
        "live_model_runs": manifest["live_model_runs"],
        "scripted_model_runs": manifest.get("scripted_model_runs", 0),
        "artifact_directory": str(output),
        "report": str(output / "scored/report.md"),
    }


def main():
    root_default = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="MCP eval toolkit — Phase 0")
    parser.add_argument("--root", type=Path, default=root_default)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate", help="validate case structure without calling a model")
    pre = sub.add_parser(
        "preflight", help="run actual MCP calls and mcp-tef case creation; no model"
    )
    run = sub.add_parser("baseline", help="run a live A/B experiment through mcp-tef")
    demo = sub.add_parser(
        "demo", help="exercise A/B scoring with scripted responses and real MCP calls; no API key"
    )
    demo.add_argument("--repeats", type=int, default=2)
    demo.set_defaults(
        provider="openai",
        model="scripted-fixture-NOT-a-real-model",
        split="dev",
        final_report=False,
        temperature=0,
        base_url=None,
    )
    offline = sub.add_parser(
        "report", help="score saved structured traces and generate a paired report"
    )
    offline.add_argument("directory", type=Path)
    offline.add_argument(
        "--reviews", type=Path, help="completed human review JSON; see scored/review-template.json"
    )
    for command in (pre, run, demo):
        command.add_argument(
            "--poker-repo", type=Path, default=root_default.parent / "poker-analytics"
        )
        command.add_argument("--tef-repo", type=Path, default=root_default.parent / "mcp-tef")
    run.add_argument(
        "--provider", choices=["openrouter", "anthropic", "openai", "ollama"], required=True
    )
    run.add_argument(
        "--model",
        required=True,
        help="explicit provider model ID; use an immutable ID when available",
    )
    run.add_argument("--base-url")
    run.add_argument(
        "--temperature",
        type=float,
        default=0,
        help="requested value; pinned upstream does not apply it",
    )
    run.add_argument("--repeats", type=int, default=1)
    run.add_argument("--split", choices=["dev", "heldout"], default="dev")
    run.add_argument("--final-report", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    output = None
    try:
        if args.command == "validate":
            suites = [
                load_suite(root / "cases" / "poker" / f"{split}.yaml")
                for split in ("dev", "heldout")
            ]
            ids = [case.id for suite in suites for case in suite.cases]
            if len(ids) != len(set(ids)):
                raise ValueError("duplicate case IDs across splits")
            print(json.dumps({suite.split: len(suite.cases) for suite in suites}, indent=2))
            return
        if args.command == "report":
            print(json.dumps(report(args.directory.resolve(), args.reviews), indent=2))
            print(f"Report: {args.directory.resolve() / 'scored/report.md'}")
            return
        if args.command in {"baseline", "demo"} and args.repeats < 1:
            raise ValueError("repeats must be at least one")
        if args.command == "baseline" and not 0 <= args.temperature <= 2:
            raise ValueError("temperature must be between zero and two")
        args.poker_repo = args.poker_repo.resolve()
        args.tef_repo = args.tef_repo.resolve()
        output = create_artifacts(root, args.command)
        print(f"Evidence: {output}", flush=True)
        if args.command == "preflight":
            summary = asyncio.run(preflight(root, args.poker_repo, args.tef_repo, output))
        else:
            summary = asyncio.run(baseline(args, root, output))
        print(json.dumps(summary, indent=2))
    except (Exception, KeyboardInterrupt) as error:
        if output:
            write_json(
                output / "failure.json", {"type": type(error).__name__, "message": str(error)}
            )
        parser.exit(1, f"{type(error).__name__}: {error}\n")


if __name__ == "__main__":
    main()
