#!/usr/bin/env python3
"""Run audit collection cycle. Designed for cron (every 5-10 min)."""

import sys
sys.path.insert(0, "/root/.openclaw/workspace/projects/_active/uaml-package")

from uaml.audit.collector import AuditCollector

DB_PATH = "/root/.openclaw/workspace/data/audit_log.db"
AGENT_ID = "Metod"

def main():
    c = AuditCollector(DB_PATH, agent_id=AGENT_ID)
    results = c.run(since_minutes=15)
    
    total = results["total_events"]
    anomalies = results["anomalies"]
    
    if total > 0 or anomalies:
        print(f"📊 Audit: {results['ssh']} SSH, {results['systemd']} systemd, {results['file_integrity']} integrity")
        if anomalies:
            for a in anomalies:
                print(f"⚠️ ANOMALY: {a['description']} ({a['count']} events, severity: {a['severity']})")
    # Silent if nothing collected

if __name__ == "__main__":
    main()
