# Installation Log — Web Server (5.189.190.7)

> Date: 2026-03-15 | Installer: Metod | Status: PARTIAL

## Server Info

| Property | Value |
|----------|-------|
| IP | `5.189.190.7` (IPv6: `2a02:c207:2313:9756::1`) |
| Hostname | `vmi3139756` |
| OS | Ubuntu 24.04.4 LTS |
| Kernel | 6.8.0-100-generic |
| CPU | 6 vCPU |
| RAM | 12 GB |
| Disk | 193 GB (4% used) |

## Pre-existing Software

- Node.js 22.22.1 ✅
- npm 10.9.4 ✅
- Python 3.12.3 ✅
- pip 24.0 ✅
- git ✅
- nginx 1.24.0 ✅
- Docker ✅ (running Umami analytics)
- OpenClaw 2026.3.8 ✅ (pre-installed, NOT configured)

## Installation Steps

### 1. SSH Key Setup
```bash
# Generated ED25519 key for inter-server communication
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N '' -C 'web-vps'
# Key added to main VPS + test server authorized_keys
```

### 2. Clone Workspace Repository
```bash
ssh-keyscan -H 5.189.139.221 >> ~/.ssh/known_hosts
cd /tmp && git clone ssh://root@5.189.139.221/root/git-repos/workspace.git uaml-workspace
```

### 3. Install UAML Package
```bash
cd /tmp/uaml-workspace/projects/_active/uaml-package
pip3 install -e . --break-system-packages
```

Result: UAML 1.0.0 installed successfully.

### 4. Run Tests
```bash
pip3 install pytest --break-system-packages
cd /tmp/uaml-workspace/projects/_active/uaml-package
python3 -m pytest tests/ -q --tb=no
```

Result: **1331 passed, 28 failed** (all failures = `ImportError: pqcrypto` — PQC library not installed).

### 5. UAML Dashboard Service
```bash
cat > /etc/systemd/system/uaml-dashboard.service << EOF
[Unit]
Description=UAML Dashboard (port 8780)
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 -c "from uaml.web.app import UAMLWebApp; UAMLWebApp(db_path=\"/tmp/uaml-workspace/data/memory.db\", agent_id=\"WebVPS\").serve(host=\"127.0.0.1\", port=8780)"
WorkingDirectory=/tmp/uaml-workspace/projects/_active/uaml-package
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable uaml-dashboard
systemctl start uaml-dashboard
```

Result: Dashboard running on `127.0.0.1:8780`, HTTP 200 verified.

## Running Services

| Service | Port | Status |
|---------|------|--------|
| nginx | 80/443 | ✅ running |
| UAML Portal | 8791 | ✅ running (systemd) |
| UAML Dashboard | 8780 | ✅ running (systemd) |
| Umami Analytics | Docker | ✅ running |
| OpenClaw Gateway | — | ❌ NOT configured (needs API keys) |

## Pending

- [ ] Anthropic API key configuration
- [ ] OpenClaw Gateway setup (`openclaw setup`)
- [ ] Decision: expose dashboard publicly? (currently localhost only)
- [ ] CDN / Cloudflare setup
- [ ] Move workspace from `/tmp/` to permanent location

---
© 2026 GLG, a.s. All rights reserved. / Všechna práva vyhrazena.
License: Non-commercial use only. Commercial use requires a paid license from GLG, a.s.

