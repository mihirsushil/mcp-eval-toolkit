"""Adapter to mcp-tef's REST API; preserve its results without relabeling its scores."""

import asyncio
import time

import httpx

from .cases import Case


SYSTEM_PROMPT = """You are a retrospective poker analytics assistant. Use the supplied tools
when stored records are needed. Use only player identities and hand identifiers supplied
in the request context. Ask for missing information before making an ambiguous personal
query. For general questions or unsupported operations, respond without calling a tool.
Do not invent missing identities, filters, or records. Use the minimum calls needed."""


def payload(case: Case, server_url: str) -> dict:
    primary = case.expected.acceptable[:1]
    return {
        "name": case.id,
        "query": case.query(),
        "expected_tool_calls": [
            {"mcp_server_url": server_url, "tool_name": call.tool, "parameters": call.arguments}
            for call in primary
        ],
        "order_dependent_matching": True,
        "available_mcp_servers": [{"url": server_url, "transport": "streamable-http"}],
    }


def adapter_limits(case: Case) -> list[str]:
    limits = ["upstream parameter score is not our case pass/fail rubric"]
    if case.expected.action == "clarify":
        limits.append("upstream no-call result does not grade clarification quality")
    if len(case.expected.acceptable) > 1:
        limits.append("only primary acceptable call exported; alternatives require manual review")
    if any(call.absent_or_null for call in case.expected.acceptable):
        limits.append("absent-or-null constraints require manual review")
    return limits


async def wait_ready(url: str, child, timeout: float = 45):
    deadline = time.monotonic() + timeout
    async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
        while time.monotonic() < deadline:
            if child.poll() is not None:
                raise RuntimeError("local server exited during startup; inspect artifact logs")
            try:
                response = await client.get(url)
                if response.status_code < 500:
                    return
            except httpx.TransportError:
                pass
            await asyncio.sleep(0.2)
    raise TimeoutError(f"server did not start: {url}")


async def create_case(client: httpx.AsyncClient, case: Case, server_url: str) -> dict:
    response = await client.post("/test-cases", json=payload(case, server_url))
    response.raise_for_status()
    return response.json()


async def execute(client, case_id: str, settings: dict, api_key: str | None) -> dict:
    headers = {"X-Model-API-Key": api_key} if api_key else {}
    response = await client.post(
        f"/test-cases/{case_id}/run", json={"model_settings": settings}, headers=headers
    )
    response.raise_for_status()
    result = response.json()
    deadline = time.monotonic() + 300
    while result["status"] not in {"completed", "failed"}:
        if time.monotonic() > deadline:
            raise TimeoutError(f"mcp-tef run {result['id']} exceeded client polling deadline")
        await asyncio.sleep(0.5)
        response = await client.get(f"/test-runs/{result['id']}")
        response.raise_for_status()
        result = response.json()
    return result
