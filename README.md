# IBM Storage Virtualize — Replication Monitor

A lightweight web-based monitor for IBM FlashSystem / SVC replication status. Connects to the IBM Storage Virtualize REST API, queries volume group replication health, and displays live results in a browser dashboard with optional auto-refresh.

---

## Features

- **Browser dashboard** — clean table showing all volume groups, link status, production/recovery sites, RPO health, and replication policy
- **Auto-refresh** — configurable polling at 30 s / 1 min / 5 min with a live countdown and progress bar
- **Flexible auth** — username/password or API token
- **Self-signed cert support** — toggle SSL verification off for FlashSystem arrays with self-signed certificates
- **Save/load config** — persist connection settings to `config.json` (password never stored)
- **Export JSON** — download the last result as a JSON file for reporting or automation
- **CLI mode** — run headless with JSON output for integration with Nagios, Prometheus, cron, etc.

---

## Requirements

- Python 3.8+
- Network access to your FlashSystem / SVC management IP on port 7443 (or 443)

---

## Quick Start

```bash
# 1. Clone or copy the project folder
cd ibm-storage-replication-monitor

# 2. Create a virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Start the web UI
python app.py
```

Open **http://127.0.0.1:5000** in your browser.

---

## Web UI Usage

1. Enter the **Host / IP** of your FlashSystem management interface (e.g. `192.168.10.50`)
2. Set the **port** — typically `7443` on newer firmware, `443` on older
3. Enter your **Username** and **Password** (or switch to the API Token tab)
4. If your array has a **self-signed certificate**, open *Advanced Options* and **uncheck** "Verify SSL Certificate"
5. Click **Run Check**
6. To enable live polling, select an interval and click **▶ Start**

> **Tip:** Click **Save Config** to persist your host/port/username settings. They reload automatically on next visit via **Load Config**.

---

## Connection Settings

| Field | Description |
|-------|-------------|
| Host / IP | Management IP or FQDN of the FlashSystem / SVC node |
| Port | `7443` (most firmware) or `443` — check your management console |
| Username | Local or LDAP account with at least *Monitor* role |
| Verify SSL | Uncheck for self-signed certificates (common on FlashSystem) |
| Timeout | Request timeout in seconds (default 30) |

---

## Replication States

The dashboard uses `link1_status` from the `/rest/v1/lsvolumegroupreplication` endpoint.

| Status | Category | Meaning |
|--------|----------|---------|
| `running` | ✅ Normal | Replication is active and healthy |
| `degraded` | ⚠ Warning | Replication degraded but continuing |
| `syncing` | ⚠ Warning | Re-synchronising after gap |
| `waiting_for_sync` | ⚠ Warning | Waiting to begin sync |
| `stopped` | ✗ Error | Replication stopped |
| `disconnected` | ✗ Error | Link to remote system lost |
| `error` / `failed` | ✗ Error | Hard failure |

Any unrecognised state is treated as Warning.

---

## CLI Usage

```bash
# Using environment variables
export IBM_SV_HOST="https://192.168.10.50:7443"
export IBM_SV_USER="admin"
export IBM_SV_PASSWORD="password"
export IBM_SV_VERIFY_SSL="false"    # for self-signed certs
python ibm_storage_replication_check.py

# Using a config file
python ibm_storage_replication_check.py --config config.json

# JSON output (for automation)
python ibm_storage_replication_check.py --output json > report.json

# Disable SSL verification
python ibm_storage_replication_check.py --no-verify-ssl

# Verbose logging
python ibm_storage_replication_check.py --verbose
```

### Exit Codes

| Code | Meaning |
|------|---------|
| `0` | All relationships normal |
| `1` | Warnings detected (or config/connection error) |
| `2` | Errors detected |
| `130` | Interrupted (Ctrl+C) |

---

## API Endpoints Used

| Purpose | Method | Endpoint |
|---------|--------|----------|
| Authenticate | `POST` | `/rest/v1/auth` |
| Volume group replication | `POST` | `/rest/v1/lsvolumegroupreplication` |

Authentication uses `X-Auth-Username` / `X-Auth-Password` request headers (not HTTP Basic Auth). The token returned is passed as `X-Auth-Token` on subsequent requests.

---

## Configuration File

Copy `config.json.example` to `config.json` and edit:

```json
{
  "host": "https://192.168.10.50",
  "port": "7443",
  "username": "admin",
  "verify_ssl": false,
  "timeout": 30
}
```

> Passwords are never written to `config.json`. You will be prompted each session.

---

## Troubleshooting

**`SSL: CERTIFICATE_VERIFY_FAILED`**
Uncheck *Verify SSL Certificate* in Advanced Options (or use `--no-verify-ssl` in CLI). FlashSystem arrays typically ship with self-signed certificates.

**`Invalid Username Header` (403)**
The array rejected HTTP Basic Auth. This is fixed — the monitor sends credentials as `X-Auth-Username` / `X-Auth-Password` headers.

**Results panel shows 0 relationships**
Ensure your account has at least *Monitor* role and that replication (Metro Mirror / Global Mirror) is configured on the array.

**`405 Method Not Allowed` on an endpoint**
IBM SV REST API requires `POST` for all `ls*` query commands, not `GET`.

---

## Security Notes

- Never commit `config.json` with real credentials to version control — add it to `.gitignore`
- Restrict file permissions: `chmod 600 config.json`
- Use a dedicated read-only service account with *Monitor* role
- Enable SSL verification in production once a valid certificate is installed

---

## File Structure

```
.
├── app.py                          # Flask web server + /api routes
├── ibm_storage_replication_check.py  # Core API client + CLI entry point
├── templates/
│   └── index.html                  # Browser dashboard (single-page)
├── requirements.txt
├── config.json.example             # Template — copy to config.json
└── README_IBM_Storage_Monitor.md
```

---

## Version History

| Version | Date | Notes |
|---------|------|-------|
| 1.2.0 | 2026-06-19 | Auto-refresh (30s/1m/5m), progress bar, pause button |
| 1.1.0 | 2026-06-19 | Web UI; fixed auth headers, SSL toggle, correct endpoint |
| 1.0.0 | 2026-06-15 | Initial CLI release |

---

*Made with IBM Bob*
