"""Run the deterministic UPG-04 Agent acceptance suite and save auditable output."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEST_FILE = ROOT / "tests" / "test_agent_scenario_suite.py"
SOURCE_FILES = tuple(sorted({
    * (ROOT / "study_task_assistant").rglob("*.py"),
    * (ROOT / "tests").rglob("*.py"),
    * (ROOT / "scripts").glob("*.py"),
    Path(__file__).resolve(),
    ROOT / "study_task_assistant" / "requirements.txt",
    ROOT / "pytest.ini",
}))
DEFAULT_OUT = ROOT / "benchmarks" / "agent_scenarios_upg04"


def _manifest() -> dict:
    source_hashes = {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in SOURCE_FILES
    }
    head_result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True,
    )
    status_result = subprocess.run(
        ["git", "status", "--short"], cwd=ROOT, text=True, capture_output=True,
    )
    return {
        "suite": "UPG-04 deterministic Agent acceptance",
        "test_file": str(TEST_FILE.relative_to(ROOT)),
        "source_sha256": source_hashes,
        "git_head": head_result.stdout.strip() if head_result.returncode == 0 else "unavailable",
        "working_tree_dirty": bool(status_result.stdout.strip()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    if args.output == DEFAULT_OUT:
        args.output = DEFAULT_OUT / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = args.output if args.output.is_absolute() else ROOT / args.output
    if output.exists() and any(output.iterdir()):
        parser.error("output must be a new or empty directory; previous evidence is never overwritten")
    output.mkdir(parents=True, exist_ok=True)
    manifest = _manifest()
    with zipfile.ZipFile(output / "source.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for path in SOURCE_FILES:
            archive.write(path, path.relative_to(ROOT))
    junit = output / "junit.xml"
    command = [sys.executable, "-m", "pytest", "-q", str(TEST_FILE), f"--junitxml={junit}"]
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    (output / "stdout.txt").write_text(completed.stdout, encoding="utf-8")
    (output / "stderr.txt").write_text(completed.stderr, encoding="utf-8")
    root = ET.parse(junit).getroot() if junit.exists() else None
    cases = []
    if root is not None:
        for case in root.iter("testcase"):
            result = "passed"
            if case.find("failure") is not None:
                result = "failed"
            elif case.find("error") is not None:
                result = "error"
            elif case.find("skipped") is not None:
                result = "skipped"
            cases.append({"name": case.attrib.get("name"), "result": result})
    report = {
        **manifest,
        "source_unchanged_during_run": manifest["source_sha256"] == _manifest()["source_sha256"],
        "command": " ".join(command),
        "exit_code": completed.returncode,
        "counts": {status: sum(case["result"] == status for case in cases)
                   for status in ("passed", "failed", "error", "skipped")},
        "cases": cases,
        "behavior_scenarios": sum(case["name"].startswith("test_agent_acceptance_scenario[") for case in cases),
        "suite_checks": sum(not case["name"].startswith("test_agent_acceptance_scenario[") for case in cases),
        "environment": {"python": sys.version, "database": "SQLite test database"},
        "limitations": [
            "SQLite behavior only; PostgreSQL checkpoint and concurrent confirmation require Docker.",
            "Model responses are deterministic MockTransport fixtures, not online quality or cost evidence.",
        ],
    }
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["counts"], ensure_ascii=False))
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
