import argparse
import asyncio
from pathlib import Path

import pytest

from mcp_eval_toolkit.cases import select_suite
from mcp_eval_toolkit.cli import baseline
from mcp_eval_toolkit.evidence import canonical_hash, write_json
from mcp_eval_toolkit.tef import SYSTEM_PROMPT

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "field,value",
    [
        (
            "requested_model_settings",
            {"provider": "openrouter", "model": "fixture", "temperature": 1},
        ),
        ("evaluation_suite_sha256", "changed-suite"),
        ("repeats", 2),
    ],
)
def test_resume_rejects_drift_before_servers_or_paid_calls(tmp_path, monkeypatch, field, value):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-fixture-not-a-credential")
    args = argparse.Namespace(
        resume=tmp_path,
        provider="openrouter",
        model="fixture",
        split="dev",
        final_report=False,
        command="baseline",
        temperature=0,
        request_limit=8,
        tool_calls_limit=5,
        base_url=None,
        repeats=3,
    )
    manifest = {
        "split": "dev",
        "repeats": 3,
        "requested_model_settings": {
            "provider": "openrouter",
            "model": "fixture",
            "temperature": 0,
            "timeout": 60,
            "max_retries": 0,
            "system_prompt": SYSTEM_PROMPT,
            "request_limit": 8,
            "tool_calls_limit": 5,
        },
        "evaluation_suite_sha256": canonical_hash(select_suite(ROOT, "dev").model_dump()),
    }
    manifest[field] = value
    write_json(tmp_path / "manifest.json", manifest)
    original = (tmp_path / "manifest.json").read_bytes()
    with pytest.raises(ValueError, match="resume requires"):
        asyncio.run(baseline(args, ROOT, tmp_path))
    assert (tmp_path / "manifest.json").read_bytes() == original
    assert not (tmp_path / "runs").exists()
