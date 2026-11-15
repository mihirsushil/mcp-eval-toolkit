"""Bind final evaluation to the inputs of a completed development experiment."""

from datetime import UTC, datetime
from pathlib import Path

from .evidence import canonical_hash, write_json
from .reporting import read_json, report


def contract(manifest: dict) -> dict:
    return {
        field: manifest[field]
        for field in (
            "sources",
            "suite_sha256",
            "experiment",
            "environments",
            "fixture",
            "tool_sha256",
            "requested_model_settings",
            "repeats",
        )
    }


def freeze(directory: Path, destination: Path) -> dict:
    if destination.exists():
        raise ValueError("freeze destination already exists; never overwrite a freeze")
    manifest = read_json(directory / "manifest.json")
    summary = report(directory)
    if manifest["kind"] != "mcp-tef-live-baseline" or manifest.get("split") != "dev":
        raise ValueError("freeze requires a live development experiment")
    if not summary["complete"] or manifest["repeats"] < 3:
        raise ValueError(
            "freeze requires complete development evidence with at least three repeats"
        )
    value = {
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "development_directory": str(directory.resolve()),
        "development_summary_sha256": canonical_hash(summary),
        "human_review_status": "pending; deterministic endpoints only",
        "contract": contract(manifest),
    }
    write_json(destination, value)
    return value


def verify_freeze(path: Path, manifest: dict):
    frozen = read_json(path)
    if frozen.get("version") != 1 or frozen.get("contract") != contract(manifest):
        raise ValueError("final evaluation differs from frozen development inputs")
    return canonical_hash(frozen)
