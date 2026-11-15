import copy

import pytest

from mcp_eval_toolkit.evidence import write_json
from mcp_eval_toolkit.freeze import contract, verify_freeze


def test_freeze_rejects_drift_in_every_experimental_input(tmp_path):
    manifest = {
        field: {"fixed": "value"}
        for field in (
            "sources",
            "suite_sha256",
            "experiment",
            "environments",
            "fixture",
            "tool_sha256",
            "requested_model_settings",
        )
    }
    manifest["repeats"] = 3
    path = tmp_path / "freeze.json"
    write_json(path, {"version": 1, "contract": contract(manifest)})
    assert len(verify_freeze(path, manifest)) == 64
    for field in contract(manifest):
        changed = copy.deepcopy(manifest)
        changed[field] = "changed"
        with pytest.raises(ValueError, match="frozen"):
            verify_freeze(path, changed)
    manifest["split"] = "heldout"
    manifest["server_urls"] = {"A": "http://new-ephemeral-port/mcp"}
    assert verify_freeze(path, manifest)
