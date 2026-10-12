"""Actual MCP discovery, fixture execution, and local mcp-tef lifecycle."""

import asyncio
import json
import os
import subprocess
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

import httpx
from jsonschema import Draft202012Validator
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

from .cases import Suite, load_suite
from .evidence import (
    available_port,
    canonical_hash,
    copy_database,
    digest,
    process,
    provenance,
    write_json,
)
from .tef import adapter_limits, create_case, wait_ready


def python_in(repo: Path) -> str:
    executable = repo / ".venv" / "bin" / "python"
    if not executable.exists():
        raise ValueError(f"missing interpreter: {executable}")
    return str(executable)


def poker_command(root: Path, poker: Path, output: Path, variant: str) -> list[str]:
    command = [
        python_in(poker),
        str(root / "scripts" / "poker_server.py"),
        "--database",
        str(output / "poker.db"),
    ]
    if variant == "B":
        command += ["--description", str(root / "experiments" / "compute-stats-description.json")]
    return command


async def snapshot_stdio(command: list[str], output: Path) -> list[dict]:
    with (output / "stdio.log").open("w") as log:
        async with stdio_client(
            StdioServerParameters(command=command[0], args=command[1:]), errlog=log
        ) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return sorted(
                    [tool.model_dump(mode="json") for tool in result.tools],
                    key=lambda tool: tool["name"],
                )


@asynccontextmanager
async def http_session(url: str):
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


def validate_cases(suites: list[Suite], tools: list[dict]) -> dict:
    schemas = {tool["name"]: tool["inputSchema"] for tool in tools}
    ids = set()
    for suite in suites:
        for case in suite.cases:
            if case.id in ids:
                raise ValueError(f"case ID reused across splits: {case.id}")
            ids.add(case.id)
            for call in case.expected.acceptable:
                if call.tool not in schemas:
                    raise ValueError(f"{case.id}: unknown tool {call.tool}")
                schema = schemas[call.tool]
                Draft202012Validator.check_schema(schema)
                Draft202012Validator(schema).validate(call.arguments)
                if not set(call.arguments).issubset(schema.get("properties", {})):
                    raise ValueError(f"{case.id}: unknown argument")
                if not set(call.absent_or_null).issubset(schema.get("properties", {})):
                    raise ValueError(f"{case.id}: unknown absent-or-null argument")
    return {
        "cases": len(ids),
        "tools": len(schemas),
        "splits": {suite.split: len(suite.cases) for suite in suites},
    }


def verify_description_only(a: list[dict], b: list[dict], target: str):
    if [tool["name"] for tool in a] != [tool["name"] for tool in b]:
        raise ValueError("experiment changed the tool set")
    changed = []
    for before, after in zip(a, b, strict=True):
        if before != after:
            if {k: v for k, v in before.items() if k != "description"} != {
                k: v for k, v in after.items() if k != "description"
            }:
                raise ValueError("experiment changed more than a description")
            changed.append(before["name"])
    if changed != [target]:
        raise ValueError(f"expected only {target} description change, found {changed}")


@asynccontextmanager
async def environment(root: Path, poker: Path, tef: Path, output: Path, scripted=False):
    fixture = copy_database(poker / "data" / "poker.db", output / "poker.db")
    manifest = {
        "kind": "infrastructure-preflight",
        "engine": "mcp-tef with process-local structured-message recording",
        "live_model_runs": 0,
        "fixture": fixture,
        "sources": {
            "toolkit": provenance(root),
            "poker": provenance(poker),
            "mcp_tef": provenance(tef),
        },
        "suite_sha256": {
            split: digest((root / "cases" / "poker" / f"{split}.yaml").read_bytes())
            for split in ("dev", "heldout")
        },
        "experiment": json.loads(
            (root / "experiments" / "compute-stats-description.json").read_text()
        ),
    }
    for name, repo in (("toolkit", root), ("poker", poker), ("mcp_tef", tef)):
        result = subprocess.run(
            [
                python_in(repo),
                "-c",
                "import importlib.metadata as m,json,sys; print(json.dumps({'python':sys.version,'packages':{d.metadata['Name']:d.version for d in m.distributions()}}))",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        manifest.setdefault("environments", {})[name] = json.loads(result.stdout)
    write_json(output / "manifest.json", manifest)
    async with AsyncExitStack() as stack:
        urls = {}
        for variant in ("A", "B"):
            port = available_port()
            command = poker_command(root, poker, output, variant) + [
                "--transport",
                "streamable-http",
                "--port",
                str(port),
            ]
            child = stack.enter_context(process(command, root, output / f"poker-{variant}.log"))
            urls[variant] = f"http://127.0.0.1:{port}/mcp"
            await wait_ready(urls[variant], child)
        tef_port = available_port()
        tef_env = {**os.environ, "DATABASE_URL": f"sqlite:///{output / 'mcp-tef.db'}"}
        command = [
            python_in(tef),
            str(root / "scripts" / "tef_server.py"),
            "--port",
            str(tef_port),
            "--traces",
            str(output / "traces"),
        ]
        if scripted:
            command.append("--scripted")
        child = stack.enter_context(process(command, tef, output / "mcp-tef.log", tef_env))
        base_url = f"http://127.0.0.1:{tef_port}"
        await wait_ready(base_url + "/health", child)
        async with httpx.AsyncClient(base_url=base_url, timeout=30, trust_env=False) as client:
            health = await client.get("/health")
            health.raise_for_status()
            if health.json().get("status") != "healthy":
                raise RuntimeError("mcp-tef did not report healthy")
            snapshots = {}
            for variant, url in urls.items():
                async with http_session(url) as session:
                    result = await session.list_tools()
                    snapshots[variant] = sorted(
                        [t.model_dump(mode="json") for t in result.tools], key=lambda t: t["name"]
                    )
                write_json(output / f"tools-{variant}.json", snapshots[variant])
            verify_description_only(snapshots["A"], snapshots["B"], manifest["experiment"]["tool"])
            manifest["tool_sha256"] = {
                key: canonical_hash(value) for key, value in snapshots.items()
            }
            manifest["server_urls"] = urls
            write_json(output / "manifest.json", manifest)
            yield client, urls, snapshots, manifest


async def preflight(root: Path, poker: Path, tef: Path, output: Path):
    async with environment(root, poker, tef, output) as (client, urls, snapshots, manifest):
        dev = load_suite(root / "cases" / "poker" / "dev.yaml")
        heldout = load_suite(root / "cases" / "poker" / "heldout.yaml")
        summary = validate_cases([dev, heldout], snapshots["A"])
        stdio = await asyncio.wait_for(
            snapshot_stdio(poker_command(root, poker, output, "A"), output), 30
        )
        if stdio != snapshots["A"]:
            raise ValueError("stdio and HTTP tool definitions differ")
        calls = []
        async with http_session(urls["A"]) as session:
            for case in dev.cases:
                if case.expected.action == "call":
                    call = case.expected.acceptable[0]
                    response = await asyncio.wait_for(
                        session.call_tool(call.tool, call.arguments), 30
                    )
                    record = {
                        "case": case.id,
                        "call": call.model_dump(),
                        "response": response.model_dump(mode="json"),
                    }
                    write_json(output / "tool-executions" / f"{case.id}.json", record)
                    if response.isError:
                        raise RuntimeError(f"{case.id}: MCP tool execution failed")
                    calls.append(case.id)
        created = []
        for case in dev.cases:
            result = await create_case(client, case, urls["A"])
            created.append(
                {"case": case.id, "upstream": result, "adapter_limits": adapter_limits(case)}
            )
        write_json(output / "mcp-tef-cases.json", created)
        with (output / "upstream-probes.log").open("w") as log:
            probe = await asyncio.create_subprocess_exec(
                python_in(tef),
                str(root / "scripts" / "probe_upstream.py"),
                "--server-url",
                urls["A"],
                "--output",
                str(output / "upstream-probes"),
                cwd=tef,
                stdout=log,
                stderr=log,
            )
            try:
                await asyncio.wait_for(probe.wait(), timeout=90)
            finally:
                if probe.returncode is None:
                    probe.terminate()
                    await probe.wait()
            if probe.returncode:
                raise RuntimeError("upstream probes failed; inspect upstream-probes.log")
        summary.update(
            {
                "development_tool_executions": len(calls),
                "mcp_tef_cases_created": len(created),
                "stdio_http_identical": True,
                "description_only_change_verified": True,
                "live_model_runs": 0,
                "heldout_model_runs": 0,
                "scripted_upstream_integration_runs": 1,
                "fixture": manifest["fixture"],
            }
        )
        write_json(output / "preflight.json", summary)
    return summary
