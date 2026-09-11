# bin/

Place `G6Scan.exe` here and the dashboard will serve it at `/download/<token>`.

It is not committed to git: it is a ~15 MB binary that changes on every build,
and Git is a poor place for those.

## Getting the file

**Automatically (recommended).** `.github/workflows/build-scanner.yml` builds it
on every push, on a Windows runner. Go to the repository's **Actions** tab, open
the latest "Build G6Scan.exe" run, and download the `G6Scan` artifact at the
bottom. Unzip it and drop `G6Scan.exe` here.

Set the repository variable `G6_SERVER_URL` to your dashboard address first
(Settings > Secrets and variables > Actions > Variables), so the scanner knows
where to send results.

**By hand, on a Windows PC:**

```powershell
pip install psutil pywin32 pyinstaller
pyinstaller --onefile --windowed --name G6Scan --add-data "data;data" scanner_app.py
```

The result lands in `dist/G6Scan.exe`.

## Hosting note

On a host with an ephemeral filesystem, a file dropped here by hand disappears
on redeploy. Either keep it on the persistent disk and point `G6_SCANNER_PATH`
at it, or commit it to a release and have the deploy fetch it.
