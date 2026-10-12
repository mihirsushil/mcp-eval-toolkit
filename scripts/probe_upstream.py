"""Run upstream behavior probes and one explicitly scripted end-to-end integration.

Use mcp-tef's interpreter. The scripted model exercises upstream agent execution,
real MCP calls and result storage; it is NOT a live model performance evaluation.
"""

import argparse
import json
import os
from pathlib import Path
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    database = args.output / "scripted-mcp-tef.db"
    if database.exists():
        parser.error("use a fresh output directory to preserve previous evidence")
    os.environ["DATABASE_URL"] = f"sqlite:///{database.resolve()}"

    from fastapi.testclient import TestClient
    from mcp_tef.api.app import app
    from mcp_tef.models.llm_models import LLMToolCall
    from mcp_tef.services.llm_service import LLMService, ToolSelectionResult
    from mcp_tef.services.tool_call_matcher import ToolCallMatcher
    from mcp_tef_models.schemas import ExpectedToolCall
    from pydantic_ai import Agent
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel

    matcher = ToolCallMatcher()

    def matched(parameters, actual):
        result = matcher.match_order_dependent(
            [
                ExpectedToolCall(
                    mcp_server_url=args.server_url, tool_name="compute_stats", parameters=parameters
                )
            ],
            [LLMToolCall(name="compute_stats", parameters=actual)],
        )[0]
        return {
            "classification": result.match_type,
            "score": result.parameter_correctness,
            "justification": result.parameter_justification,
        }

    probes = {
        "kind": "scripted-infrastructure-probes",
        "live_model_runs": 0,
        "empty_expected_with_invented_player": matched({}, {"player_hash": "invented"}),
        "right_tool_wrong_argument": matched({"position": "BTN"}, {"position": "BB"}),
        "valid_optional_argument": matched(
            {"position": "BTN"}, {"position": "BTN", "player_hash": None}
        ),
        "no_call_classification": matcher.match_order_independent([], [])[0].match_type,
    }
    service = LLMService("openai", "scripted-probe", "not-a-key", timeout=7, max_retries=0)
    with (
        patch("mcp_tef.services.llm_service.OpenAIProvider"),
        patch("mcp_tef.services.llm_service.OpenAIChatModel"),
        patch("mcp_tef.services.llm_service.Agent") as factory,
    ):
        service.make_agent(system_prompt="probe", output_type=ToolSelectionResult)
        probes["agent_keyword_arguments"] = sorted(factory.call_args.kwargs)
        probes["model_settings_forwarded"] = "model_settings" in factory.call_args.kwargs

    turns = []

    def scripted_model(messages, info):
        turns.append(
            {
                "message_count": len(messages),
                "available_tools": [tool.name for tool in info.function_tools],
            }
        )
        if len(turns) == 1:
            return ModelResponse(parts=[ToolCallPart("compute_stats", {}, tool_call_id="probe-1")])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name, {"confidence": "high"}, tool_call_id="probe-final"
                )
            ]
        )

    def scripted_agent(self, **kwargs):
        return Agent(FunctionModel(scripted_model), **kwargs)

    with patch.object(LLMService, "make_agent", scripted_agent), TestClient(app) as client:
        response = client.post(
            "/test-cases",
            json={
                "name": "scripted-integration-population-stats",
                "query": "Compute population statistics.",
                "expected_tool_calls": [
                    {
                        "mcp_server_url": args.server_url,
                        "tool_name": "compute_stats",
                        "parameters": {},
                    }
                ],
                "available_mcp_servers": [args.server_url],
                "order_dependent_matching": True,
            },
        )
        response.raise_for_status()
        case_id = response.json()["id"]
        response = client.post(
            f"/test-cases/{case_id}/run",
            json={
                "model_settings": {
                    "provider": "openai",
                    "model": "scripted-fixture-NOT-a-real-model",
                    "temperature": 0,
                }
            },
        )
        response.raise_for_status()
        run_id = response.json()["id"]
        response = client.get(f"/test-runs/{run_id}")
        response.raise_for_status()
        result = response.json()
        (args.output / "scripted-run.json").write_text(json.dumps(result, indent=2) + "\n")
        if result["status"] != "completed" or result["classification"] != "TP":
            raise RuntimeError(f"scripted integration failed: {result['status']}")
        probes["scripted_integration"] = {
            "status": result["status"],
            "classification": result["classification"],
            "turns": turns,
        }
    (args.output / "probes.json").write_text(json.dumps(probes, indent=2) + "\n")
    print(json.dumps(probes, indent=2))


if __name__ == "__main__":
    main()
