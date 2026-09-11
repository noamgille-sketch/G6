#!/usr/bin/env python3
"""Run a single G6 Guard scan from the command line.

Usage:
    python run_scan.py

Then open the dashboard (python dashboard/app.py) to browse history and
finding details, or just read the summary printed below.
"""
import sys

from g6_anticheat.engine import run_scan

SEVERITY_COLOR = {
    "INFO": "\033[36m",
    "LOW": "\033[32m",
    "MEDIUM": "\033[33m",
    "HIGH": "\033[31m",
    "CRITICAL": "\033[1;31m",
}
RESET = "\033[0m"


def main():
    print("G6 Guard - running scan...\n")
    result = run_scan()

    findings = sorted(result["findings"], key=lambda f: f["severity"], reverse=True)

    if not findings:
        print("No findings. Nothing suspicious detected by the current checks.\n")
    else:
        for f in findings:
            color = SEVERITY_COLOR.get(f["severity_label"], "")
            print(f"[{color}{f['severity_label']}{RESET}] {f['title']}")
            print(f"    {f['detail']}\n")

    print("=" * 60)
    print(f"VERDICT : {result['verdict']}   ({result['risk_score']}/100)")
    print("=" * 60)
    print(result["verdict_detail"])
    if result["detected_cheats"]:
        print("\nCheats identifies : " + ", ".join(result["detected_cheats"]))
    print("-" * 60)
    print("\nRun 'python dashboard/app.py' and open http://127.0.0.1:5151 for the full dashboard.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
