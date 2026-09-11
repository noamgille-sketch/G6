#!/usr/bin/env python3
"""G6 Guard - verification client.

Someone sent you a verification link and asked you to check your PC for
FiveM cheats. This script does exactly that and nothing else:

    python verify_client.py <the link they sent you>

It shows you what it is going to send, writes the full report to a file
on your own disk so you can read every line of it yourself, and only
uploads it after you type YES. Nothing leaves your machine before that.
"""
import argparse
import json
import os
import sys
import textwrap
import urllib.error
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from g6_anticheat import profile as profiles
from g6_anticheat.engine import build_report

TIMEOUT = 30


def parse_link(link: str) -> tuple[str, str]:
    """Accept a full /verify/<token> URL and split it into (base_url, token)."""
    link = link.strip().rstrip("/")
    if "/verify/" not in link:
        raise SystemExit(
            "That does not look like a verification link.\n"
            "Expected something like: https://example.com/verify/AbCd1234..."
        )
    base, token = link.rsplit("/verify/", 1)
    if not token:
        raise SystemExit("The link is missing its token.")
    return base.rstrip("/"), token


def http_get_json(url: str):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_post_json(url: str, payload: dict):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def print_consent(manifest: dict, base_url: str):
    asked_by = manifest.get("label") or "Quelqu'un"
    print("=" * 70)
    print(f"  {asked_by} te demande de vérifier ce PC (cheats FiveM).")
    print(f"  Le rapport sera envoyé à : {base_url}")
    print("=" * 70)

    print("\n" + "*" * 70)
    print("  " + (manifest.get("privacy_headline") or profiles.PRIVACY_HEADLINE).upper())
    print("*" * 70)
    summary = manifest.get("privacy_summary") or profiles.PRIVACY_SUMMARY
    for line in textwrap.wrap(summary, width=68):
        print(f"  {line}")

    if manifest.get("note"):
        print(f"\n  Son message : {manifest['note']}")

    print("\nCE QUI EST REGARDÉ ET ENVOYÉ :")
    for item in manifest.get("collects") or profiles.REMOTE_COLLECTS:
        print(f"  + {item}")

    print("\nCE QUI N'EST JAMAIS TOUCHÉ :")
    for item in manifest.get("never_collects") or profiles.REMOTE_NEVER_COLLECTS:
        print(f"  - {item}")

    print(
        "\nLe rapport complet est d'abord écrit dans un fichier sur TON disque."
        "\nTu peux l'ouvrir et lire chaque ligne avant que quoi que ce soit soit envoyé."
    )


def save_report(report: dict) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.abspath(f"g6-report-{stamp}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    return path


def summarise(report: dict):
    findings = report["findings"]
    print("\n" + "=" * 70)
    print(f"  VERDICT : {report['verdict']}  ({report['risk_score']}/100)")
    print("=" * 70)
    for line in textwrap.wrap(report["verdict_detail"], width=68):
        print(f"  {line}")

    if report["detected_cheats"]:
        print("\n  Cheats identifiés : " + ", ".join(report["detected_cheats"]))

    print(f"\n{len(findings)} élément(s) à envoyer :\n")
    if not findings:
        print("  (rien de suspect trouvé)")
    for f in findings:
        print(f"  [{f['severity_label']}] {f['title']}")


def ask_yes(prompt: str) -> bool:
    answer = input(f"\n{prompt} [yes/no]: ").strip().lower()
    return answer in ("y", "yes", "o", "oui")


def main():
    parser = argparse.ArgumentParser(description="Run a G6 Guard verification scan")
    parser.add_argument("link", help="the verification link you were sent")
    parser.add_argument("--name", help="display name shown to the person who asked")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="scan and write the report to disk, never upload it",
    )
    args = parser.parse_args()

    base_url, token = parse_link(args.link)

    try:
        manifest = http_get_json(f"{base_url}/api/verify/{token}")
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"The link was rejected by the server ({exc.code}). Ask for a fresh one.")
    except urllib.error.URLError as exc:
        raise SystemExit(f"Could not reach {base_url}: {exc.reason}")

    if manifest.get("status") == "expired":
        raise SystemExit("This verification link has expired. Ask for a new one.")
    if manifest.get("status") == "completed":
        raise SystemExit("This link has already been used. Ask for a new one.")
    if manifest.get("status") == "revoked":
        raise SystemExit("This link was revoked by the person who created it.")

    print_consent(manifest, base_url)

    if not args.dry_run and not ask_yes("Run the scan?"):
        raise SystemExit("Cancelled. Nothing was scanned, nothing was sent.")

    display_name = args.name or input("\nDisplay name to show with the result: ").strip() or "anonymous"

    print("\nScanning... (this takes a few seconds)")
    report = build_report("remote")
    report["client_label"] = display_name

    summarise(report)
    path = save_report(report)
    print(f"\nFull report written to:\n  {path}")

    if args.dry_run:
        print("\n--dry-run: nothing was uploaded.")
        return 0

    if not ask_yes("Send this report now?"):
        print("Not sent. The file above stays on your disk; delete it whenever you want.")
        return 0

    try:
        result = http_post_json(f"{base_url}/api/verify/{token}/submit", report)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise SystemExit(f"Upload refused ({exc.code}): {detail}")
    except urllib.error.URLError as exc:
        raise SystemExit(f"Could not reach {base_url}: {exc.reason}")

    print(f"\nSent. Result: {result.get('risk_score')}/100 - {result.get('risk_label')}")
    print("This link is now used up and cannot be submitted again.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
