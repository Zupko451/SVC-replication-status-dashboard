#!/usr/bin/env python3
"""
IBM Storage Virtualize Replication Monitor - Web Frontend
Flask application that provides a browser-based UI to configure and run
the replication status check against IBM FlashSystem / Storage Virtualize arrays.
"""

import os
import json
import logging
from datetime import datetime
from flask import Flask, render_template, request, jsonify

import urllib3

try:
    import requests
    from requests.adapters import HTTPAdapter
    from requests.packages.urllib3.util.retry import Retry
except ImportError:
    raise SystemExit("Error: 'requests' library is required. Run: pip install requests flask colorama")

# Inline the core client logic so the web app is self-contained
from ibm_storage_replication_check import (
    IBMStorageVirtualizeClient,
    StatusAnalyzer,
    Config,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.urandom(24)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

class WebConfig:
    """Lightweight config object built from a form POST (no env/file required)."""

    def __init__(self, form: dict):
        host = form.get("host", "").strip()
        port = form.get("port", "").strip()
        if port and port not in ("443", ""):
            self.host = f"https://{host}:{port}"
        else:
            self.host = f"https://{host}" if not host.startswith(("http://", "https://")) else host

        self.host = self.host.rstrip("/")
        self.username = form.get("username", "").strip()
        self.password = form.get("password", "")
        self.token = form.get("token", "").strip() or None
        self.verify_ssl = form.get("verify_ssl", "true").lower() == "true"
        self.timeout = int(form.get("timeout", 30))
        self.log_level = "INFO"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/check", methods=["POST"])
def run_check():
    """Run replication check and return JSON results."""
    data = request.get_json(force=True)

    # Basic validation
    host = (data.get("host") or "").strip()
    if not host:
        return jsonify({"success": False, "error": "Host / IP address is required."}), 400

    use_token = bool((data.get("token") or "").strip())
    if not use_token:
        if not (data.get("username") or "").strip():
            return jsonify({"success": False, "error": "Username is required when not using a token."}), 400
        if not data.get("password"):
            return jsonify({"success": False, "error": "Password is required when not using a token."}), 400

    try:
        logger.info("POST /api/check payload: host=%s port=%s user=%s token_present=%s verify_ssl=%s",
                    data.get("host"), data.get("port"), data.get("username"),
                    bool((data.get("token") or "").strip()), data.get("verify_ssl"))

        cfg = WebConfig(data)
        logger.info("WebConfig resolved: host=%s verify_ssl=%s", cfg.host, cfg.verify_ssl)

        if not cfg.verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        client = IBMStorageVirtualizeClient(cfg)

        # Authenticate
        if not client.authenticate():
            # Give a specific hint when the failure is SSL-related
            ssl_hint = (
                " The array uses a self-signed certificate — uncheck "
                "\"Verify SSL Certificate\" in Advanced Options and retry."
            ) if cfg.verify_ssl else ""
            return jsonify({"success": False, "error": f"Authentication failed. Check credentials and host.{ssl_hint}"}), 401

        # Fetch relationships
        relationships = client.get_rc_relationships()
        client.close()

        if relationships is None:
            return jsonify({"success": False, "error": "Failed to retrieve replication relationships from the array."}), 502

        summary = StatusAnalyzer.analyze_relationships(relationships)

        return jsonify({
            "success": True,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "host": cfg.host,
            "summary": {
                "total": summary["total"],
                "normal": summary["normal"],
                "warning": summary["warning"],
                "error": summary["error"],
            },
            "relationships": [
                {
                    "name": d["name"],
                    "state": d["state"],
                    "category": d["category"],
                    "primary_vdisk": d["primary_vdisk"],
                    "secondary_vdisk": d["secondary_vdisk"],
                    "within_rpo": d.get("within_rpo", ""),
                    "policy": d.get("policy", "N/A"),
                }
                for d in summary["details"]
            ],
        })

    except Exception as exc:
        logger.exception("Error during replication check")
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route("/api/save-config", methods=["POST"])
def save_config():
    """Save connection settings to config.json (password excluded)."""
    data = request.get_json(force=True)
    config_out = {
        "host": (data.get("host") or "").strip(),
        "port": (data.get("port") or "443").strip(),
        "username": (data.get("username") or "").strip(),
        "verify_ssl": data.get("verify_ssl", True),
        "timeout": int(data.get("timeout", 30)),
        "log_level": "INFO",
    }
    try:
        with open("config.json", "w") as f:
            json.dump(config_out, f, indent=2)
        return jsonify({"success": True, "message": "config.json saved (password not stored)."})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route("/api/load-config")
def load_config():
    """Load saved connection settings from config.json."""
    try:
        with open("config.json") as f:
            cfg = json.load(f)
        # Strip any stored password for safety
        cfg.pop("password", None)
        return jsonify({"success": True, "config": cfg})
    except FileNotFoundError:
        return jsonify({"success": False, "error": "No saved config found."})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


if __name__ == "__main__":
    print("\n  IBM Storage Virtualize Replication Monitor")
    print("  Open your browser at: http://127.0.0.1:5000\n")
    app.run(debug=True, host="0.0.0.0", port=5000)
