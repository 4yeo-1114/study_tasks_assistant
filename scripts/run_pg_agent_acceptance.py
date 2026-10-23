"""Run acceptance in a fresh, temporary pgvector container; keep evidence, no secrets."""

import argparse
import json
import os
import secrets
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from run_agent_scenarios import ROOT, SOURCE_FILES, _manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full-suite", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or ROOT / "benchmarks" / "pg_agent_upg04" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    if output.exists() and any(output.iterdir()):
        parser.error("output must be new or empty")
    output.mkdir(parents=True, exist_ok=True)
    manifest = _manifest()
    with zipfile.ZipFile(output / "source.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for path in SOURCE_FILES:
            archive.write(path, path.relative_to(ROOT))
    name = "upg04-test-" + secrets.token_hex(8)
    password = secrets.token_urlsafe(24)
    # A unique container without a volume; never reset a user's existing database.
    created = subprocess.run([
        "docker", "run", "-d", "--name", name, "-e", "POSTGRES_USER=study",
        "-e", "POSTGRES_PASSWORD=" + password, "-e", "POSTGRES_DB=study_tasks_test",
        "-p", "127.0.0.1::5432", "pgvector/pgvector:pg17",
    ], capture_output=True, text=True)
    if created.returncode:
        # Do not include process args (which contain the generated password).
        raise RuntimeError("Could not start temporary pgvector container: " + created.stderr)
    try:
        for _ in range(60):
            ready = subprocess.run(["docker", "exec", name, "pg_isready", "-U", "study"], capture_output=True)
            if ready.returncode == 0:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("Temporary PostgreSQL did not become ready within 30 seconds")
        info = json.loads(subprocess.check_output(["docker", "inspect", name], text=True))[0]
        port = info["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostPort"]
        env = os.environ.copy()
        env["TEST_DATABASE_URL"] = f"postgresql+psycopg://study:{password}@127.0.0.1:{port}/study_tasks_test"
        command = [sys.executable, "-m", "pytest", "-q", "--tb=short", f"--junitxml={output / 'junit.xml'}"]
        if not args.full_suite:
            command += ["tests/test_postgres_agent_runtime.py", "tests/test_postgres_integration.py"]
        result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
        stdout, stderr = result.stdout.replace(password, "[redacted]"), result.stderr.replace(password, "[redacted]")
        (output / "stdout.txt").write_text(stdout, encoding="utf-8")
        (output / "stderr.txt").write_text(stderr, encoding="utf-8")
        report = {**manifest, "command": command, "exit_code": result.returncode,
                  "source_unchanged_during_run": manifest["source_sha256"] == _manifest()["source_sha256"],
                  "environment": {"python": sys.version, "image": info["Config"]["Image"], "image_id": info["Image"],
                                  "database": "study_tasks_test", "temporary_container": True},
                  "limitations": ["Deterministic model fixtures; no online quality, cost or production performance claims."]}
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(stdout)
        if stderr:
            print(stderr, file=sys.stderr)
        print("Evidence:", output)
        return result.returncode
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=True)


if __name__ == "__main__":
    raise SystemExit(main())
