"""Run from the repository root using the project Python interpreter."""
import argparse
import csv
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "study_task_assistant"))
from knowledge.retrieval_baseline import load_dataset, run_keyword, snapshot_source, summarize


def git(*args):
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "benchmarks/retrieval_smoke.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    options = parser.parse_args()
    dataset = load_dataset(options.dataset)
    # Exclusive creation keeps an earlier experiment immutable.
    options.output.mkdir(parents=True, exist_ok=False)
    snapshot = snapshot_source(ROOT, options.output / "snapshot")
    rows = run_keyword(dataset, k=options.k, rounds=options.rounds, warmups=options.warmups)
    metadata = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "strategy": "in_memory_keyword",
        "scope": "synthetic smoke, not PostgreSQL or production Agent latency",
        "dataset_kind": dataset.get("dataset_kind"),
        "dataset_sha256": hashlib.sha256(options.dataset.read_bytes()).hexdigest(),
        "source_sha256": snapshot["source_sha256"],
        "git_head": git("rev-parse", "HEAD"),
        "git_status": git("status", "--porcelain"),
        "python": sys.version, "platform": platform.platform(),
        "processor": platform.processor(),
        "packages": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()},
        "k": options.k, "rounds": options.rounds, "warmups": options.warmups,
        "chunk_count": len(dataset["chunks"]), "query_count": len(dataset["cases"]),
        "command": sys.argv,
    }
    for name, value in [("metadata.json", metadata), ("raw.json", rows), ("dataset.json", dataset), ("summary.json", summarize(rows))]:
        (options.output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    with (options.output / "raw.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows({**row, "actual_chunks": json.dumps(row["actual_chunks"], ensure_ascii=False)} for row in rows)
    # Preserve runner and fixture alongside the application source snapshot.
    (options.output / "runner.py").write_bytes(Path(__file__).read_bytes())
    print(json.dumps(summarize(rows), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
