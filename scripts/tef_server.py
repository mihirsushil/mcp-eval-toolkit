"""Local mcp-tef launcher with lossless agent-message recording.

The hooks are process-local; upstream source and sampling behavior are unchanged.
The optional scripted provider exists only for the explicitly labeled demo.
"""

import argparse
import json
from contextvars import ContextVar
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--traces", type=Path, required=True)
    parser.add_argument("--scripted", action="store_true")
    args = parser.parse_args()
    args.traces.mkdir(parents=True, exist_ok=True)

    import uvicorn
    from mcp_tef.api import test_cases
    from mcp_tef.api.app import app
    from mcp_tef.services import llm_service
    from mcp_tef.services.evaluation_service import EvaluationService
    from pydantic_ai import Agent

    current_run = ContextVar("toolkit_run", default=None)

    class RecordingAgent(Agent):
        async def run(self, *positional, **kwargs):
            result = await super().run(*positional, **kwargs)
            run_id = current_run.get()
            if run_id is not None:
                trace = {
                    "version": 1,
                    "kind": "scripted" if args.scripted else "live",
                    "upstream_run_id": run_id,
                    "messages": json.loads(result.all_messages_json()),
                }
                with (args.traces / f"{run_id}.json").open("x") as output:
                    json.dump(trace, output, indent=2)
                    output.write("\n")
            return result

    class RecordingEvaluationService(EvaluationService):
        async def execute_pending_test(self, test_run, api_key):
            token = current_run.set(test_run.id)
            try:
                return await super().execute_pending_test(test_run, api_key)
            finally:
                current_run.reset(token)

    test_cases.EvaluationService = RecordingEvaluationService
    llm_service.Agent = RecordingAgent

    if args.scripted:
        from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
        from pydantic_ai.models.function import FunctionModel

        def make_scripted_agent(self, **kwargs):
            """Fixed demonstration responses; these do not predict model behavior."""
            turn = 0

            def respond(messages, info):
                nonlocal turn
                turn += 1
                descriptions = {tool.name: tool.description for tool in info.function_tools}
                variant_b = "personal statistics" in descriptions.get("compute_stats", "")
                query = str(messages[0].parts[-1].content)
                parts = []
                if turn == 1 and "entire population" in query:
                    arguments = {} if variant_b else {"player_hash": "invented"}
                    parts = [ToolCallPart("compute_stats", arguments, tool_call_id="demo-call")]
                elif turn == 1 and "small blind" in query:
                    arguments = {
                        "player_hash": "376d6fd36aec498b",
                        "position": "BB" if variant_b else "SB",
                    }
                    parts = [ToolCallPart("compute_stats", arguments, tool_call_id="demo-call")]
                elif turn == 1 and "What is my VPIP?" in query and not variant_b:
                    parts = [ToolCallPart("compute_stats", {}, tool_call_id="demo-call")]
                else:
                    text = (
                        "What is your player_hash?"
                        if "What is my VPIP?" in query
                        else "VPIP means voluntarily put money in pot."
                    )
                    parts = [
                        TextPart(text),
                        ToolCallPart(
                            info.output_tools[0].name,
                            {"confidence": "high"},
                            tool_call_id="demo-final",
                        ),
                    ]
                return ModelResponse(parts=parts)

            return RecordingAgent(FunctionModel(respond), **kwargs)

        llm_service.LLMService.make_agent = make_scripted_agent

    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
