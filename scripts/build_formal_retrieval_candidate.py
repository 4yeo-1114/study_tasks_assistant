"""Build the 120-case candidate retrieval dataset."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "study_task_assistant"))

from knowledge.formal_dataset import build_formal_candidate
from knowledge.retrieval_baseline import load_dataset

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "benchmarks/retrieval_candidate_v1.json")
    args = parser.parse_args()
    base = load_dataset(ROOT / "benchmarks/retrieval_smoke.json")
    candidate = build_formal_candidate(base)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(candidate, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "cases": len(candidate["cases"]),
                      "development": 40, "frozen": 80,
                      "review_status": candidate["review_status"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
