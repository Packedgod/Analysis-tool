"""read_file run-dir resolution: basename fallback and clear errors."""

import json
import tempfile
from pathlib import Path

from src.tools.read_file_tool import ReadFileTool

# Real run dirs live under agent/runs (an allowed run root); tmp dirs elsewhere
# are rejected by safe_run_dir, so tests must create the run dir there.
_RUNS = Path(__file__).resolve().parents[1] / "runs"


def _run_dir() -> Path:
    _RUNS.mkdir(exist_ok=True)
    return Path(tempfile.mkdtemp(dir=str(_RUNS)))


def test_reads_manifest_at_run_dir_root() -> None:
    rd = _run_dir()
    try:
        (rd / "analysis_backbone.json").write_text('{"status": "ready"}', encoding="utf-8")
        out = json.loads(ReadFileTool().execute(path="analysis_backbone.json", run_dir=str(rd)))
        assert out["status"] == "ok"
        assert '"ready"' in out["content"]
    finally:
        __import__("shutil").rmtree(rd, ignore_errors=True)


def test_basename_fallback_finds_run_dir_root_file() -> None:
    """A stray subdir prefix still resolves to the run-dir-root file."""
    rd = _run_dir()
    try:
        (rd / "analysis_backbone.json").write_text("{}", encoding="utf-8")
        out = json.loads(
            ReadFileTool().execute(path="artifacts/analysis_backbone.json", run_dir=str(rd))
        )
        assert out["status"] == "ok"
    finally:
        __import__("shutil").rmtree(rd, ignore_errors=True)


def test_missing_file_gives_clear_not_found_error() -> None:
    rd = _run_dir()
    try:
        out = json.loads(ReadFileTool().execute(path="nope.json", run_dir=str(rd)))
        assert out["status"] == "error"
        assert "not found" in out["error"]
    finally:
        __import__("shutil").rmtree(rd, ignore_errors=True)
