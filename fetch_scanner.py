#!/usr/bin/env python3
"""Fetch G6Scan.exe from the latest GitHub release, at deploy time.

A hosted dashboard has no persistent disk and no way to upload a file by
hand, so the scanner cannot simply be dropped into bin/. Instead the
build step pulls it from the repository's latest release, where the
Windows build workflow attaches it.

Never fails the deploy: if there is no release yet, or the repo is
private and no token is available, it says so and exits cleanly. The
dashboard already handles a missing scanner - the verification page tells
the visitor it is not ready instead of offering a broken download.

Configure with:
    G6_REPO        owner/repo (Render sets RENDER_GIT_REPO_SLUG for you)
    GITHUB_TOKEN   only needed for a private repository
"""
import json
import os
import sys
import urllib.error
import urllib.request

ASSET_NAME = "G6Scan.exe"
DEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin", ASSET_NAME)
TIMEOUT = 60


def repo_slug() -> str | None:
    direct = os.environ.get("G6_REPO")
    if direct:
        return direct.strip().strip("/")

    # Render exposes the clone URL of the service's repository.
    url = os.environ.get("RENDER_GIT_REPO_SLUG") or os.environ.get("RENDER_GIT_REPO_URL")
    if not url:
        return None
    slug = url.rstrip("/").removesuffix(".git")
    parts = slug.split("/")
    return "/".join(parts[-2:]) if len(parts) >= 2 else None


def request(url: str, token: str | None, accept: str):
    headers = {"Accept": accept, "User-Agent": "g6-guard-deploy"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.urlopen(
        urllib.request.Request(url, headers=headers), timeout=TIMEOUT
    )


def main() -> int:
    slug = repo_slug()
    if not slug:
        print("fetch_scanner: repository unknown (set G6_REPO=owner/repo). Skipping.")
        return 0

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("G6_GITHUB_TOKEN")
    api = f"https://api.github.com/repos/{slug}/releases/latest"

    try:
        with request(api, token, "application/vnd.github+json") as resp:
            release = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            print(f"fetch_scanner: no release published on {slug} yet. Skipping.")
        elif exc.code in (401, 403):
            print("fetch_scanner: no access to the releases (private repo needs "
                  "GITHUB_TOKEN). Skipping.")
        else:
            print(f"fetch_scanner: GitHub returned {exc.code}. Skipping.")
        return 0
    except (urllib.error.URLError, ValueError) as exc:
        print(f"fetch_scanner: could not reach GitHub ({exc}). Skipping.")
        return 0

    asset = next(
        (a for a in release.get("assets", []) if a.get("name") == ASSET_NAME), None
    )
    if not asset:
        print(f"fetch_scanner: release '{release.get('tag_name')}' has no {ASSET_NAME}. "
              "Has the build workflow finished? Skipping.")
        return 0

    os.makedirs(os.path.dirname(DEST), exist_ok=True)
    try:
        with request(asset["url"], token, "application/octet-stream") as resp:
            data = resp.read()
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        print(f"fetch_scanner: download failed ({exc}). Skipping.")
        return 0

    if not data.startswith(b"MZ"):
        print("fetch_scanner: downloaded file is not a Windows executable. Skipping.")
        return 0

    with open(DEST, "wb") as fh:
        fh.write(data)

    print(f"fetch_scanner: {ASSET_NAME} installed from release "
          f"'{release.get('tag_name')}' ({len(data) / 1024 / 1024:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
