# UAML + OpenClaw — Instalační log (Testovací server)

**Server:** `161.97.184.185` (vmi3139676)
**Datum:** 2026-03-15
**Instaloval:** Cyril (AI agent, Notebook1)
**OS:** Ubuntu 24.04.4 LTS (Noble Numbat)
**HW:** 6 vCPU, 12 GB RAM, 193 GB SSD

## Nainstalované předpoklady

| Balíček | Verze |
|---------|-------|
| Python | 3.12.3 |
| Node.js | 22.22.1 |
| npm | 10.9.4 |
| git | 2.43.0 |
| ufw | aktivní |
| fail2ban | nainstalováno |

## Instalační kroky

### 1. Aktualizace systému
```bash
apt update && apt upgrade -y
```

### 2. Instalace Node.js 22
```bash
curl -fsSL https://deb.nodesource.com/setup_22.x -o /tmp/nodesource_setup.sh
bash /tmp/nodesource_setup.sh
apt install -y nodejs
```

### 3. Instalace OpenClaw
```bash
npm install -g openclaw
# Výsledek: OpenClaw 2026.3.13 (61d171a)
```

### 4. Klonování workspace
```bash
# Generování SSH klíče pro přístup k repozitáři
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N '' -C 'test-server'
# Přidat veřejný klíč do authorized_keys na VPS
# Poté klonovat:
git clone ssh://root@5.189.139.221/root/git-repos/workspace.git /root/.openclaw/workspace
```

### 5. Instalace UAML
```bash
cd /root/.openclaw/workspace/projects/_active/uaml-package
pip install -e . --break-system-packages
# Výsledek: uaml-1.0.0 nainstalováno
```

### 6. Instalace systemd služby OpenClaw
```bash
openclaw gateway install
# Automaticky generuje autentizační token brány
# Instaluje: ~/.config/systemd/user/openclaw-gateway.service
```

### 7. Spuštění brány
```bash
openclaw gateway start
# Služba: systemd (povolena)
# Port: 18789
# Logy: /tmp/openclaw/openclaw-2026-03-15.log
```

### 8. Firewall
```bash
ufw allow ssh
ufw allow 443/tcp
ufw allow 80/tcp
ufw --force enable
```

### 9. Posílení zabezpečení
```bash
chmod 700 /root/.openclaw
```

## Ověření

### Výsledky testů
```
1331 passed, 28 failed in 73.01s
```
- 28 selhání je v PQC testech (chybí knihovna `oqs` — post-kvantová kryptografie)
- Všechny testy jádra, Focus Engine, API, webu, compliance a federace prošly

### Spuštěné služby
- OpenClaw Gateway: systemd, povoleno, port 18789
- UAML: importovatelné, verze 1.0.0

## Čekající konfigurace
- [ ] Anthropic API klíč pro model Claude
- [ ] Nastavení Discord/Telegram kanálu
- [ ] Port UAML Dashboardu + systemd služba
- [ ] nginx reverse proxy (pokud je potřeba veřejný přístup)
- [ ] SSL certifikát (Let's Encrypt)
- [ ] Instalace PQC knihovny (`liboqs-python`) pro plnou kryptografickou sadu

## Poznámky
- Čistá instalace od nuly trvala ~10 minut
- Server je na Ubuntu 24.04 se 6 vCPU / 12 GB RAM
- 191 GB volného místa na disku
- Přístup pouze přes SSH klíče (ověřování heslem vypnuto)

---
© 2026 GLG, a.s. All rights reserved. / Všechna práva vyhrazena.
License: Non-commercial use only. Commercial use requires a paid license from GLG, a.s.
