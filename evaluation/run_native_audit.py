#!/usr/bin/env python3
"""Re-run independent native projection tests on current code and a Git revision.

Example: python3 evaluation/run_native_audit.py --baseline 21ad414 --out evaluation/fidelity-baseline-native.json
No network, provider SDK, API key or target-module execution is needed.
"""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parent.parent
RUNNER = '''import json, unittest
suite = unittest.defaultTestLoader.loadTestsFromName("tests.test_fidelity_adversarial.TestNativeProjection")
result = unittest.TestResult()
suite.run(result)
groups = {}
for kind, entries in (("failures", result.failures), ("errors", result.errors)):
    for test, trace in entries:
        name = test.id().split(" (")[0]
        lines = [line for line in trace.splitlines() if line.strip()]
        group = groups.setdefault(name, {"failures": 0, "errors": 0, "sample": lines[-1][:240] if lines else ""})
        group[kind] += 1
print(json.dumps({"tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors), "by_test": groups}, ensure_ascii=False))
'''


def run(directory: Path) -> dict:
    completed = subprocess.run([sys.executable, "-c", RUNNER], cwd=directory,
                               capture_output=True, text=True, check=True)
    return json.loads(completed.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", help="Local Git revision to compare, e.g. 21ad414")
    parser.add_argument("--out", type=Path, help="JSON report path")
    args = parser.parse_args()
    report = {"scope": "Direct-module native tests; preservation capsules are bypassed.",
              "current": run(ROOT)}
    if args.baseline:
        revision = subprocess.check_output(["git", "rev-parse", args.baseline], cwd=ROOT, text=True).strip()
        archive = subprocess.check_output(["git", "archive", revision], cwd=ROOT)
        with tempfile.TemporaryDirectory(prefix="bridge-native-baseline-") as tmp:
            directory = Path(tmp)
            with tarfile.open(fileobj=io.BytesIO(archive)) as source:
                source.extractall(directory, filter="data")
            tests = (ROOT / "tests/test_fidelity_adversarial.py").read_text()
            tests = tests.replace("from converter.preservation import CAPSULE_DIR, PreservationError\n", "")
            (directory / "tests/test_fidelity_adversarial.py").write_text(tests)
            report["baseline"] = {"revision": revision, **run(directory)}
    output = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output)
    print(output, end="")
    return bool(report["current"]["failures"] or report["current"]["errors"])


if __name__ == "__main__":
    raise SystemExit(main())
