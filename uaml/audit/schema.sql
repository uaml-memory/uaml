-- UAML Audit Log Schema v1.0
-- Centralized security event logging for certification (ISO 27001, GDPR)

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    source TEXT NOT NULL,          -- 'ssh', 'firewall', 'uaml_api', 'dashboard', 'systemd', 'file_integrity', 'learner', 'neo4j'
    severity TEXT NOT NULL DEFAULT 'info',  -- 'debug', 'info', 'warning', 'critical', 'alert'
    category TEXT NOT NULL,        -- 'auth', 'access', 'modification', 'network', 'service', 'integrity', 'anomaly'
    agent_id TEXT,                 -- which agent/machine generated this
    hostname TEXT,                 -- machine hostname
    event_type TEXT NOT NULL,      -- specific event: 'ssh_login_failed', 'api_knowledge_create', 'file_hash_changed', etc.
    summary TEXT NOT NULL,         -- human-readable description
    details TEXT,                  -- JSON blob with full event data
    source_file TEXT,              -- original log file path
    source_line INTEGER,           -- line number in source file
    remote_ip TEXT,                -- remote IP if applicable
    user_id TEXT,                  -- user/agent involved
    raw_line TEXT,                 -- original log line for forensics
    content_hash TEXT,             -- SHA-256 of the event for tamper detection
    neo4j_synced INTEGER DEFAULT 0,  -- 0=pending, 1=synced as Incident node
    neo4j_node_id TEXT             -- Neo4j node ID after sync
);

CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_source ON audit_events(source);
CREATE INDEX IF NOT EXISTS idx_audit_severity ON audit_events(severity);
CREATE INDEX IF NOT EXISTS idx_audit_category ON audit_events(category);
CREATE INDEX IF NOT EXISTS idx_audit_event_type ON audit_events(event_type);
CREATE INDEX IF NOT EXISTS idx_audit_neo4j_synced ON audit_events(neo4j_synced);

-- Anomaly rules table — configurable detection patterns
CREATE TABLE IF NOT EXISTS anomaly_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    source TEXT NOT NULL,           -- which log source this rule applies to
    pattern TEXT NOT NULL,          -- detection pattern (regex or threshold expression)
    threshold INTEGER DEFAULT 1,   -- how many events trigger the anomaly
    window_seconds INTEGER DEFAULT 300,  -- time window for threshold
    severity TEXT DEFAULT 'warning',
    enabled INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now'))
);

-- Pre-loaded anomaly rules
INSERT OR IGNORE INTO anomaly_rules (name, description, source, pattern, threshold, window_seconds, severity) VALUES
    ('ssh_brute_force', 'Multiple failed SSH login attempts', 'ssh', 'Failed password|Invalid user', 5, 300, 'critical'),
    ('ssh_root_login', 'Root SSH login (should be key-only)', 'ssh', 'Accepted password.*root', 1, 60, 'alert'),
    ('api_unknown_ip', 'API access from non-whitelisted IP', 'uaml_api', 'unknown_ip', 1, 60, 'warning'),
    ('service_restart_loop', 'Service restarting repeatedly', 'systemd', 'Started.*Stopped.*Started', 3, 300, 'warning'),
    ('file_integrity_fail', 'Critical file hash mismatch', 'file_integrity', 'hash_changed', 1, 60, 'critical'),
    ('db_external_modify', 'DB modified outside known process', 'file_integrity', 'db_modified_external', 1, 60, 'alert'),
    ('firewall_port_scan', 'Multiple blocked connections from same IP', 'firewall', 'DPT=', 10, 60, 'warning'),
    ('unusual_outbound', 'Unexpected outbound connection', 'firewall', 'outbound_unknown', 1, 60, 'warning');

-- Tracked files for integrity monitoring
CREATE TABLE IF NOT EXISTS monitored_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL UNIQUE,
    last_hash TEXT,                 -- SHA-256 of file content
    last_size INTEGER,
    last_modified TEXT,
    last_checked TEXT,
    alert_on_change INTEGER DEFAULT 1
);

-- Pre-load critical files to monitor
INSERT OR IGNORE INTO monitored_files (file_path, alert_on_change) VALUES
    ('/root/.openclaw/workspace/data/memory.db', 1),
    ('/root/.openclaw/workspace/todo.db', 1),
    ('/root/.openclaw/openclaw.json', 1),
    ('/root/.ssh/authorized_keys', 1),
    ('/etc/passwd', 1),
    ('/etc/shadow', 1),
    ('/etc/ssh/sshd_config', 1);

-- Incidents table — aggregated security events with log back-references
CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    detected_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    type TEXT NOT NULL,              -- brute_force, port_scan, service_crash, config_drift, unauthorized_access, privilege_escalation
    severity TEXT NOT NULL,          -- low, medium, high, critical
    title TEXT NOT NULL,
    description TEXT,
    log_refs TEXT,                   -- JSON array of audit_event IDs
    metadata TEXT,                   -- JSON extra data (source_ips, rule name, etc.)
    resolved INTEGER DEFAULT 0,
    resolved_at TEXT,
    resolved_by TEXT,
    neo4j_synced INTEGER DEFAULT 0,
    neo4j_node_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_incident_type ON incidents(type);
CREATE INDEX IF NOT EXISTS idx_incident_severity ON incidents(severity);
CREATE INDEX IF NOT EXISTS idx_incident_detected ON incidents(detected_at);
CREATE INDEX IF NOT EXISTS idx_incident_resolved ON incidents(resolved);
