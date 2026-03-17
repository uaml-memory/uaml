# UAML + OpenClaw Installation — Test Server

**Server:** `161.97.184.185` (vmi3139676)
**Date:** 2026-03-15
**Installed by:** Cyril (AI agent, Notebook1)
**OS:** Ubuntu 24.04.4 LTS (Noble Numbat)
**HW:** 6 vCPU, 12 GB RAM, 193 GB SSD

## Prerequisites Installed

| Package | Version |
|---------|---------|
| Python | 3.12.3 |
| Node.js | 22.22.1 |
| npm | 10.9.4 |
| git | 2.43.0 |
| ufw | active |
| fail2ban | installed |

## Installation Steps

### 1. System Update
```bash
apt update && apt upgrade -y
```

### 2. Install Node.js 22
```bash
curl -fsSL https://deb.nodesource.com/setup_22.x -o /tmp/nodesource_setup.sh
bash /tmp/nodesource_setup.sh
apt install -y nodejs
```

### 3. Install OpenClaw
```bash
npm install -g openclaw
# Result: OpenClaw 2026.3.13 (61d171a)
```

### 4. Clone Workspace
```bash
# Generate SSH key for repo access
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N '' -C 'test-server'
# Add public key to VPS authorized_keys
# Then clone:
git clone ssh://root@5.189.139.221/root/git-repos/workspace.git /root/.openclaw/workspace
```

### 5. Install UAML
```bash
cd /root/.openclaw/workspace/projects/_active/uaml-package
pip install -e . --break-system-packages
# Result: uaml-1.0.0 installed
```

### 6. Install OpenClaw systemd service
```bash
openclaw gateway install
# Auto-generates gateway auth token
# Installs: ~/.config/systemd/user/openclaw-gateway.service
```

### 7. Start Gateway
```bash
openclaw gateway start
# Service: systemd (enabled)
# Port: 18789
# Logs: /tmp/openclaw/openclaw-2026-03-15.log
```

### 8. Firewall
```bash
ufw allow ssh
ufw allow 443/tcp
ufw allow 80/tcp
ufw --force enable
```

### 9. Security Hardening
```bash
chmod 700 /root/.openclaw
```

## Verification

### Test Results
```
1331 passed, 28 failed in 73.01s
```
- 28 failures are in PQC tests (missing `oqs` library — post-quantum crypto)
- All core, Focus Engine, API, web, compliance, federation tests pass

### Services Running
- OpenClaw Gateway: systemd, enabled, port 18789
- UAML: importable, 1.0.0

## Pending Configuration
- [ ] Anthropic API key for Claude model
- [ ] Discord/Telegram channel setup
- [ ] UAML Dashboard port + systemd service
- [ ] nginx reverse proxy (if public access needed)
- [ ] SSL certificate (Let's Encrypt)
- [ ] PQC library installation (`liboqs-python`) for full crypto suite

## Notes
- Clean install from zero took ~10 minutes
- Server is on Ubuntu 24.04 with 6 vCPU / 12 GB RAM
- 191 GB free disk space
- SSH key-based access only (password auth disabled)

---
© 2026 GLG, a.s. All rights reserved. / Všechna práva vyhrazena.
License: Non-commercial use only. Commercial use requires a paid license from GLG, a.s.

