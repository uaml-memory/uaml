# Instalační log — Webový server (5.189.190.7)

> Datum: 2026-03-15 | Instaloval: Metod | Stav: ČÁSTEČNÉ

## Informace o serveru

| Vlastnost | Hodnota |
|-----------|---------|
| IP | `5.189.190.7` (IPv6: `2a02:c207:2313:9756::1`) |
| Hostname | `vmi3139756` |
| OS | Ubuntu 24.04.4 LTS |
| Jádro | 6.8.0-100-generic |
| CPU | 6 vCPU |
| RAM | 12 GB |
| Disk | 193 GB (4% využito) |

## Předinstalovaný software

- Node.js 22.22.1 ✅
- npm 10.9.4 ✅
- Python 3.12.3 ✅
- pip 24.0 ✅
- git ✅
- nginx 1.24.0 ✅
- Docker ✅ (spuštěna analytika Umami)
- OpenClaw 2026.3.8 ✅ (předinstalováno, NENAKONFIGUROVÁNO)

## Instalační kroky

### 1. Nastavení SSH klíče
```bash
# Vygenerován ED25519 klíč pro meziserverovou komunikaci
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N '' -C 'web-vps'
# Klíč přidán do authorized_keys na hlavním VPS + testovacím serveru
```

### 2. Klonování workspace repozitáře
```bash
ssh-keyscan -H 5.189.139.221 >> ~/.ssh/known_hosts
cd /tmp && git clone ssh://root@5.189.139.221/root/git-repos/workspace.git uaml-workspace
```

### 3. Instalace balíčku UAML
```bash
cd /tmp/uaml-workspace/projects/_active/uaml-package
pip3 install -e . --break-system-packages
```

Výsledek: UAML 1.0.0 nainstalováno úspěšně.

### 4. Spuštění testů
```bash
pip3 install pytest --break-system-packages
cd /tmp/uaml-workspace/projects/_active/uaml-package
python3 -m pytest tests/ -q --tb=no
```

Výsledek: **1331 prošlo, 28 selhalo** (všechna selhání = `ImportError: pqcrypto` — PQC knihovna není nainstalována).

### 5. Systemd služba UAML Dashboardu
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

Výsledek: Dashboard běží na `127.0.0.1:8780`, ověřeno HTTP 200.

## Spuštěné služby

| Služba | Port | Stav |
|--------|------|------|
| nginx | 80/443 | ✅ spuštěno |
| UAML Portál | 8791 | ✅ spuštěno (systemd) |
| UAML Dashboard | 8780 | ✅ spuštěno (systemd) |
| Umami Analytics | Docker | ✅ spuštěno |
| OpenClaw Gateway | — | ❌ NENAKONFIGUROVÁNO (vyžaduje API klíče) |

## Čekající

- [ ] Konfigurace Anthropic API klíče
- [ ] Nastavení OpenClaw Gateway (`openclaw setup`)
- [ ] Rozhodnutí: zpřístupnit dashboard veřejně? (momentálně pouze localhost)
- [ ] Nastavení CDN / Cloudflare
- [ ] Přesun workspace z `/tmp/` na trvalé umístění

---
© 2026 GLG, a.s. All rights reserved. / Všechna práva vyhrazena.
License: Non-commercial use only. Commercial use requires a paid license from GLG, a.s.
