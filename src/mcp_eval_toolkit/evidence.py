"""Local evidence storage and reproducibility metadata."""

import hashlib
import json
import socket
import sqlite3
import subprocess
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_hash(value) -> str:
    return digest(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def git_output(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else "uncommitted"


def provenance(repo: Path) -> dict:
    files = (
        subprocess.check_output(
            ["git", "-C", str(repo), "ls-files", "--cached", "--others", "--exclude-standard", "-z"]
        )
        .decode()
        .split("\0")
    )
    hashes = {
        name: digest((repo / name).read_bytes())
        for name in sorted(set(files))
        if name and (repo / name).is_file()
    }
    return {
        "path": str(repo),
        "commit": git_output(repo, "rev-parse", "HEAD"),
        "status": git_output(repo, "status", "--porcelain"),
        "source_sha256": canonical_hash(hashes),
        "file_sha256": hashes,
    }


def create_artifacts(root: Path, kind: str) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    path = root / "artifacts" / f"{kind}-{stamp}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def copy_database(source: Path, target: Path) -> dict:
    if not source.is_file() or target.exists():
        raise ValueError("fixture source must exist and destination must be new")
    with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as original:
        with sqlite3.connect(target) as copy:
            original.backup(copy)
            hands = copy.execute("SELECT COUNT(*) FROM hands").fetchone()[0]
            player_exists = copy.execute(
                "SELECT COUNT(*) FROM hand_seats WHERE player_hash = ?",
                ("376d6fd36aec498b",),
            ).fetchone()[0]
    if not player_exists:
        raise ValueError("suite's public-fixture player is missing from this database")
    return {"sha256": digest(target.read_bytes()), "hands": hands, "player_seats": player_exists}


def available_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextmanager
def process(command: list[str], cwd: Path, log: Path, env=None):
    with log.open("w") as output:
        child = subprocess.Popen(command, cwd=cwd, stdout=output, stderr=output, env=env)
        try:
            yield child
        finally:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
