#!/usr/bin/env python3
import argparse
import functools
import os
import secrets
import sys
import threading
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import (
    Flask, abort, jsonify, render_template, request, redirect, session, url_for,
)
from werkzeug.middleware.proxy_fix import ProxyFix

from g6_anticheat import auth, db, profile as profiles
from g6_anticheat.engine import persist_report, run_scan
from g6_anticheat.submission import InvalidSubmission, clean_report

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024  # a report is a few KB

# Sessions. A generated key is fine for local use, but on a deployment it
# must be set, otherwise every restart logs everyone out.
app.secret_key = os.environ.get("G6_SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.environ.get("G6_HTTPS", "1") == "1"
                               and os.environ.get("G6_LOCAL") != "1"),
)

# Behind a host's proxy, so url_for/request.url_root produce the real
# https:// address instead of http://internal-container.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

_scan_lock = threading.Lock()


def login_required(view):
    """Protect owner-only pages. No-op when no accounts are configured."""
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not auth.auth_configured():
            return view(*args, **kwargs)
        if not session.get("user"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


@app.context_processor
def inject_globals():
    return {
        "current_user": session.get("user"),
        "auth_configured": auth.auth_configured(),
    }


@app.route("/login", methods=["GET", "POST"])
def login():
    if not auth.auth_configured():
        return redirect(url_for("index"))

    error = None
    if request.method == "POST":
        ip = request.remote_addr or "-"
        locked = auth.is_locked_out(ip)
        if locked:
            error = f"Trop de tentatives. Réessaie dans {locked // 60 + 1} minute(s)."
        else:
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""
            if auth.verify(username, password, ip):
                session.clear()
                session["user"] = username
                session.permanent = True
                target = request.args.get("next") or url_for("index")
                # Only allow relative redirects - never bounce to another site.
                if not target.startswith("/") or target.startswith("//"):
                    target = url_for("index")
                return redirect(target)
            error = "Identifiant ou mot de passe incorrect."

    return render_template("login.html", error=error)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))

SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
DEFAULT_LINK_HOURS = 24


def _public_base_url() -> str:
    """Base URL handed to the person you send the link to.

    Set G6_PUBLIC_URL when the dashboard is reachable through a tunnel or a
    port forward - otherwise the generated link points at 127.0.0.1, which
    only works on your own machine.
    """
    configured = os.environ.get("G6_PUBLIC_URL")
    if configured:
        return configured.rstrip("/")
    return request.url_root.rstrip("/")


def _verification_link(token: str) -> str:
    return f"{_public_base_url()}/verify/{token}"


def _sorted(findings):
    return sorted(findings, key=lambda f: SEVERITY_ORDER.index(f["severity_label"]))


def _is_expired(verification) -> bool:
    expires_at = verification.get("expires_at")
    if not expires_at:
        return False
    try:
        return datetime.now(timezone.utc) > datetime.fromisoformat(expires_at)
    except ValueError:
        return False


@app.route("/")
@login_required
def index():
    db.init_db()
    return render_template(
        "index.html",
        scans=db.list_scans(limit=25),
        verifications=db.list_verifications(limit=25),
        base_url=_public_base_url(),
        base_url_is_local="127.0.0.1" in _public_base_url() or "localhost" in _public_base_url(),
    )


@app.route("/scan/<int:scan_id>")
@login_required
def scan_detail(scan_id):
    db.init_db()
    scan = db.get_scan(scan_id)
    if not scan:
        abort(404)
    return render_template(
        "scan_detail.html",
        scan=scan,
        findings=_sorted(db.get_findings(scan_id)),
        statuses=db.get_check_statuses(scan_id),
    )


@app.route("/scan/new")
@login_required
def trigger_and_redirect():
    if _scan_lock.acquire(blocking=False):
        try:
            result = run_scan()
        finally:
            _scan_lock.release()
        return redirect(url_for("scan_detail", scan_id=result["scan_id"]))
    return redirect(url_for("index"))


# --- Verification links -------------------------------------------------


@app.route("/verifications/new", methods=["POST"])
@login_required
def create_verification():
    db.init_db()
    label = (request.form.get("label") or "").strip()[:80] or None
    note = (request.form.get("note") or "").strip()[:300] or None
    hours = request.form.get("hours", type=int) or DEFAULT_LINK_HOURS
    hours = max(1, min(hours, 24 * 14))

    token = secrets.token_urlsafe(32)
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
    vid = db.create_verification(token, label, note, expires_at)
    return redirect(url_for("verification_detail", verification_id=vid))


@app.route("/verification/<int:verification_id>")
@login_required
def verification_detail(verification_id):
    db.init_db()
    verification = db.get_verification(verification_id)
    if not verification:
        abort(404)

    findings, statuses, scan = [], [], None
    if verification["scan_id"]:
        scan = db.get_scan(verification["scan_id"])
        findings = _sorted(db.get_findings(verification["scan_id"]))
        statuses = db.get_check_statuses(verification["scan_id"])

    return render_template(
        "verification_detail.html",
        v=verification,
        link=_verification_link(verification["token"]),
        expired=_is_expired(verification),
        scan=scan,
        findings=findings,
        statuses=statuses,
    )


@app.route("/verification/<int:verification_id>/revoke", methods=["POST"])
@login_required
def revoke_verification(verification_id):
    db.revoke_verification(verification_id)
    return redirect(url_for("verification_detail", verification_id=verification_id))


@app.route("/verify/<token>")
def verify_landing(token):
    """What the person you sent the link to sees."""
    db.init_db()
    verification = db.get_verification_by_token(token)
    if not verification:
        abort(404)

    return render_template(
        "verify_landing.html",
        v=verification,
        token=token,
        link=_verification_link(token),
        expired=_is_expired(verification),
        collects=profiles.REMOTE_COLLECTS,
        never_collects=profiles.REMOTE_NEVER_COLLECTS,
        privacy_headline=profiles.PRIVACY_HEADLINE,
        privacy_summary=profiles.PRIVACY_SUMMARY,
    )


@app.route("/api/verify/<token>")
def verify_manifest(token):
    """Consulted by the client before it scans, so it can show what it will send."""
    db.init_db()
    verification = db.get_verification_by_token(token)
    if not verification:
        return jsonify({"error": "unknown verification link"}), 404

    return jsonify({
        "label": verification["label"],
        "note": verification["note"],
        "status": "expired" if _is_expired(verification) else verification["status"],
        "privacy_headline": profiles.PRIVACY_HEADLINE,
        "privacy_summary": profiles.PRIVACY_SUMMARY,
        "collects": profiles.REMOTE_COLLECTS,
        "never_collects": profiles.REMOTE_NEVER_COLLECTS,
    })


@app.route("/api/verify/<token>/submit", methods=["POST"])
def verify_submit(token):
    db.init_db()
    verification = db.get_verification_by_token(token)
    if not verification:
        return jsonify({"error": "unknown verification link"}), 404
    if verification["status"] != "pending":
        return jsonify({"error": f"this link is already {verification['status']}"}), 409
    if _is_expired(verification):
        return jsonify({"error": "this link has expired"}), 410

    try:
        report = clean_report(request.get_json(silent=True))
    except InvalidSubmission as exc:
        return jsonify({"error": str(exc)}), 400

    client_label = report["client_label"] or verification["label"]
    scan_id = persist_report(report, source="remote", client_label=client_label)
    db.complete_verification(token, scan_id, client_label, report["platform"])

    return jsonify({
        "ok": True,
        "verdict": report["verdict"],
        "risk_score": report["risk_score"],
        "risk_label": report["risk_label"],
        "findings_sent": len(report["findings"]),
    })


def main():
    parser = argparse.ArgumentParser(description="G6 Guard dashboard")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="bind address; use 0.0.0.0 only when you intend to expose the dashboard",
    )
    parser.add_argument("--port", type=int, default=5151)
    args = parser.parse_args()

    db.init_db()
    if args.host != "127.0.0.1":
        print(f"WARNING: binding to {args.host} - this dashboard has no login. "
              "Prefer a tunnel (cloudflared/ngrok) over exposing it directly.\n")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
