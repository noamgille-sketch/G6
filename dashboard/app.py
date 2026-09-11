#!/usr/bin/env python3
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, jsonify, render_template, redirect, url_for

from g6_anticheat import db
from g6_anticheat.engine import run_scan

app = Flask(__name__)
_scan_lock = threading.Lock()

SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]


@app.route("/")
def index():
    db.init_db()
    scans = db.list_scans(limit=25)
    return render_template("index.html", scans=scans)


@app.route("/scan/<int:scan_id>")
def scan_detail(scan_id):
    db.init_db()
    scan = db.get_scan(scan_id)
    if not scan:
        return "Scan not found", 404
    findings = db.get_findings(scan_id)
    findings.sort(key=lambda f: SEVERITY_ORDER.index(f["severity_label"]))
    statuses = db.get_check_statuses(scan_id)
    return render_template(
        "scan_detail.html", scan=scan, findings=findings, statuses=statuses, severity_order=SEVERITY_ORDER
    )


@app.route("/api/scan", methods=["POST"])
def api_trigger_scan():
    if not _scan_lock.acquire(blocking=False):
        return jsonify({"error": "a scan is already running"}), 409
    try:
        result = run_scan()
        return jsonify(result)
    finally:
        _scan_lock.release()


@app.route("/scan/new")
def trigger_and_redirect():
    if _scan_lock.acquire(blocking=False):
        try:
            result = run_scan()
        finally:
            _scan_lock.release()
        return redirect(url_for("scan_detail", scan_id=result["scan_id"]))
    return redirect(url_for("index"))


if __name__ == "__main__":
    db.init_db()
    app.run(host="127.0.0.1", port=5151, debug=False)
