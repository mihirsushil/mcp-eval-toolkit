import asyncio

import httpx
import pytest

from mcp_eval_toolkit.tef import execute


def test_pending_run_is_polled_and_raw_result_preserved():
    seen = []
    result = {"id": "run-1", "status": "completed", "llm_response_raw": "full transcript"}

    def handle(request):
        seen.append(request)
        if request.method == "POST":
            assert request.headers["X-Model-API-Key"] == "test-fixture-key"
            return httpx.Response(200, json={"id": "run-1", "status": "pending"})
        assert request.url.path == "/test-runs/run-1"
        assert "X-Model-API-Key" not in request.headers
        return httpx.Response(200, json=result)

    async def run():
        async with httpx.AsyncClient(
            base_url="http://fixture", transport=httpx.MockTransport(handle)
        ) as client:
            return await execute(client, "case-1", {"model": "fixture"}, "test-fixture-key")

    assert asyncio.run(run()) == result
    assert len(seen) == 2


def test_failed_upstream_run_is_returned_without_turning_it_into_a_pass():
    failure = {"id": "run-1", "status": "failed", "error_message": "provider unavailable"}

    async def run():
        async with httpx.AsyncClient(
            base_url="http://fixture",
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=failure)),
        ) as client:
            return await execute(client, "case-1", {}, None)

    assert asyncio.run(run()) == failure


def test_http_failure_is_not_scored():
    async def run():
        async with httpx.AsyncClient(
            base_url="http://fixture",
            transport=httpx.MockTransport(lambda _: httpx.Response(503)),
        ) as client:
            return await execute(client, "case-1", {}, None)

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(run())
