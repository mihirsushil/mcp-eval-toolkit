"""Strict checks of actual structured messages, independent of upstream TP scores."""

import json
from dataclasses import dataclass

from jsonschema import Draft202012Validator

from .cases import Case
from .evidence import canonical_hash


class EvidenceError(ValueError):
    """The trace cannot safely be interpreted as a complete observation."""


@dataclass
class Observation:
    calls: list[dict]
    text: str
    retries: int


def observe(trace: dict, run_id: str, scripted: bool) -> Observation:
    if trace.get("version") != 1 or trace.get("upstream_run_id") != run_id:
        raise EvidenceError("trace version or upstream run ID mismatch")
    if trace.get("kind") != ("scripted" if scripted else "live"):
        raise EvidenceError("scripted/live evidence mismatch")
    messages = trace.get("messages")
    if not isinstance(messages, list) or not messages:
        raise EvidenceError("missing structured messages")
    calls, text, pending = [], [], {}
    seen_ids = set()
    retries = 0
    final_seen = False
    for message in messages:
        if not isinstance(message, dict) or message.get("kind") not in {"request", "response"}:
            raise EvidenceError("malformed message")
        parts = message.get("parts")
        if not isinstance(parts, list):
            raise EvidenceError("missing message parts")
        for part in parts:
            if not isinstance(part, dict):
                raise EvidenceError("malformed message part")
            kind = part.get("part_kind")
            if kind not in {
                "system-prompt",
                "user-prompt",
                "text",
                "thinking",
                "tool-call",
                "tool-return",
                "retry-prompt",
            }:
                raise EvidenceError(f"unrecognized message part: {kind}")
            if kind == "text" and message["kind"] == "response":
                text.append(str(part.get("content", "")))
            elif kind == "tool-call":
                if message["kind"] != "response":
                    raise EvidenceError("tool call outside model response")
                name, call_id = part.get("tool_name"), part.get("tool_call_id")
                if not isinstance(name, str) or not isinstance(call_id, str) or call_id in seen_ids:
                    raise EvidenceError("missing or duplicate tool-call identity")
                seen_ids.add(call_id)
                if "args" not in part:
                    raise EvidenceError("tool arguments missing from trace")
                arguments = part["args"]
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        pass  # Preserve malformed model output so it fails the argument check.
                call = {"tool": name, "arguments": arguments, "call_id": call_id, "error": False}
                pending[call_id] = call
                if name != "final_result":
                    calls.append(call)
            elif kind in {"tool-return", "retry-prompt"}:
                call_id = part.get("tool_call_id")
                if kind == "retry-prompt":
                    retries += 1
                if call_id is None and kind == "retry-prompt":
                    continue
                if message["kind"] != "request" or call_id not in pending:
                    raise EvidenceError("tool return without a matching call")
                call = pending.pop(call_id)
                if part.get("tool_name") != call["tool"]:
                    raise EvidenceError("tool return name does not match call")
                content = part.get("content")
                call["error"] = kind == "retry-prompt" or (
                    isinstance(content, dict) and content.get("isError") is True
                )
                if call["tool"] == "final_result" and not call["error"]:
                    final_seen = True
    if pending or not final_seen:
        raise EvidenceError("trace lacks a completed structured final result")
    return Observation(calls, "\n".join(text), retries)


def equal_json(left, right) -> bool:
    """JSON bools must not compare equal to Python integer 1 or 0."""
    return canonical_hash(left) == canonical_hash(right)


def check_call(expected, actual: dict, schema: dict) -> list[str]:
    arguments = actual["arguments"]
    if not isinstance(arguments, dict):
        return ["tool arguments are not a valid JSON object"]
    reasons = []
    for error in Draft202012Validator(schema).iter_errors(arguments):
        reasons.append(f"schema: {error.message}")
    properties = schema.get("properties", {})
    for name, value in expected.arguments.items():
        effective = arguments.get(name, properties.get(name, {}).get("default"))
        if not equal_json(effective, value):
            reasons.append(f"{name}: expected {value!r}, received {effective!r}")
    for name in expected.absent_or_null:
        if arguments.get(name) is not None:
            reasons.append(f"{name}: must be omitted or null")
    for name, value in arguments.items():
        if name not in properties:
            reasons.append(f"unknown argument: {name}")
        elif name not in expected.arguments and name not in expected.absent_or_null:
            prop = properties[name]
            if "default" not in prop or not equal_json(value, prop["default"]):
                reasons.append(f"unrequested non-default argument: {name}")
    return reasons


def score(case: Case, result: dict, trace: dict | None, tools: list[dict], scripted=False) -> dict:
    verdict = {
        "case_id": case.id,
        "status": "error",
        "deterministic_pass": None,
        "reasons": [],
        "rubric": case.expected.rubric,
        "review_required": case.expected.action != "call",
        "text": "",
    }
    if result.get("status") != "completed":
        verdict["reasons"] = [f"upstream status: {result.get('status', 'missing')}"]
        return verdict
    try:
        if trace is None:
            raise EvidenceError(
                "structured trace missing; legacy null arguments are not evidence of {}"
            )
        observed = observe(trace, result["id"], scripted)
        schemas = {tool["name"]: tool["inputSchema"] for tool in tools}
        if "final_result" in schemas:
            raise EvidenceError("server tool conflicts with reserved final_result output tool")
        verdict["text"] = observed.text
        verdict["calls"] = observed.calls
        reasons = []
        if observed.retries:
            reasons.append(f"{observed.retries} validation/tool retries")
        if any(call["error"] for call in observed.calls):
            reasons.append("tool returned an error")
        if case.expected.action != "call":
            if observed.calls:
                reasons.append(f"expected no tool calls, received {len(observed.calls)}")
        elif len(observed.calls) != 1:
            reasons.append(f"expected exactly one tool call, received {len(observed.calls)}")
        else:
            actual = observed.calls[0]
            alternatives = [
                call for call in case.expected.acceptable if call.tool == actual["tool"]
            ]
            if not alternatives:
                reasons.append(f"unexpected tool: {actual['tool']}")
            elif actual["tool"] not in schemas:
                raise EvidenceError("tool schema missing")
            else:
                candidates = [
                    check_call(call, actual, schemas[actual["tool"]]) for call in alternatives
                ]
                if not any(not candidate for candidate in candidates):
                    reasons.extend(min(candidates, key=len))
        verdict.update(status="scored", deterministic_pass=not reasons, reasons=reasons)
    except (EvidenceError, KeyError, TypeError, ValueError) as error:
        verdict["reasons"] = [str(error)]
    return verdict
