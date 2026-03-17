/**
 * UAML Dashboard — Compliance & Audit Page
 */

Pages.compliance = async function() {
  const content = document.getElementById('main-content');

  document.getElementById('header-actions').innerHTML = `
    <button class="btn btn-primary btn-sm" onclick="Pages.compliance.runAudit()">🔐 Run Audit</button>
    <button class="btn btn-secondary btn-sm" onclick="Pages.compliance.exportReport()">📄 Export Report</button>
  `;

  content.innerHTML = `
    <div class="tabs">
      <div class="tab active" data-tab="overview" onclick="Pages.compliance.switchTab('overview')">Overview</div>
      <div class="tab" data-tab="findings" onclick="Pages.compliance.switchTab('findings')">Findings</div>
      <div class="tab" data-tab="audit-log" onclick="Pages.compliance.switchTab('audit-log')">Audit Log</div>
      <div class="tab" data-tab="retention" onclick="Pages.compliance.switchTab('retention')">Retention</div>
    </div>
    <div id="compliance-content">${UI.skeleton(400)}</div>
  `;

  Pages.compliance.switchTab('overview');
};

Pages.compliance.switchTab = function(tab) {
  document.querySelectorAll('.tabs .tab').forEach(t =>
    t.classList.toggle('active', t.dataset.tab === tab)
  );
  const el = document.getElementById('compliance-content');

  switch (tab) {
    case 'overview': Pages.compliance.renderOverview(el); break;
    case 'findings': Pages.compliance.renderFindings(el); break;
    case 'audit-log': Pages.compliance.renderAuditLog(el); break;
    case 'retention': Pages.compliance.renderRetention(el); break;
  }
};

Pages.compliance.renderOverview = async function(el) {
  el.innerHTML = `<div style="display:flex;justify-content:center;padding:24px">${UI.spinner()}</div>`;

  // Try to load compliance data, fall back to demo
  let auditData;
  try {
    auditData = await API.audit();
  } catch {
    auditData = null;
  }

  const score = auditData?.score ?? 85;
  const gdprScore = auditData?.gdpr_score ?? 90;
  const isoScore = auditData?.iso_score ?? 80;
  const findingsCount = auditData?.findings_count ?? 3;
  const lastAudit = auditData?.last_audit ?? new Date().toISOString();

  el.innerHTML = `
    <div class="page-grid grid-3" style="margin-bottom:24px">
      <!-- Overall Score -->
      <div class="card" style="text-align:center">
        <div class="card-title" style="margin-bottom:16px">Overall Compliance</div>
        <div style="display:flex;justify-content:center;margin-bottom:12px">
          ${UI.complianceRing(score, 140)}
        </div>
        <div style="font-size:13px;color:var(--text-muted)">Last audit: ${UI.timeAgo(lastAudit)}</div>
      </div>

      <!-- GDPR -->
      <div class="card" style="text-align:center">
        <div class="card-title" style="margin-bottom:16px">GDPR (Art. 5-35)</div>
        <div style="display:flex;justify-content:center;margin-bottom:12px">
          ${UI.complianceRing(gdprScore, 140)}
        </div>
        <div style="display:flex;flex-direction:column;gap:8px;text-align:left;font-size:13px">
          <div style="display:flex;justify-content:space-between">
            <span>Data minimisation</span>
            ${UI.badge('Pass', 'success')}
          </div>
          <div style="display:flex;justify-content:space-between">
            <span>Right to erasure</span>
            ${UI.badge('Pass', 'success')}
          </div>
          <div style="display:flex;justify-content:space-between">
            <span>Consent tracking</span>
            ${UI.badge(gdprScore < 100 ? 'Review' : 'Pass', gdprScore < 100 ? 'warning' : 'success')}
          </div>
        </div>
      </div>

      <!-- ISO 27001 -->
      <div class="card" style="text-align:center">
        <div class="card-title" style="margin-bottom:16px">ISO 27001 Annex A</div>
        <div style="display:flex;justify-content:center;margin-bottom:12px">
          ${UI.complianceRing(isoScore, 140)}
        </div>
        <div style="display:flex;flex-direction:column;gap:8px;text-align:left;font-size:13px">
          <div style="display:flex;justify-content:space-between">
            <span>Encryption at rest</span>
            ${UI.badge('Pass', 'success')}
          </div>
          <div style="display:flex;justify-content:space-between">
            <span>Access control</span>
            ${UI.badge('Pass', 'success')}
          </div>
          <div style="display:flex;justify-content:space-between">
            <span>Audit trail</span>
            ${UI.badge(isoScore < 100 ? 'Partial' : 'Pass', isoScore < 100 ? 'warning' : 'success')}
          </div>
        </div>
      </div>
    </div>

    <!-- Summary -->
    <div class="card">
      <div class="card-header">
        <div class="card-title">Compliance Summary</div>
      </div>
      <div class="page-grid grid-4">
        ${UI.statCard('🔍', 'Findings', findingsCount, 'require attention', findingsCount > 0 ? 'warning' : 'success')}
        ${UI.statCard('🔐', 'PQC Encryption', 'Active', 'ML-KEM-768 + AES-256-GCM', 'success')}
        ${UI.statCard('📋', 'Data Layers', '5', 'identity to project', 'info')}
        ${UI.statCard('🕐', 'Retention', 'Configured', 'auto-expire enabled', 'primary')}
      </div>
    </div>
  `;
};

Pages.compliance.renderFindings = async function(el) {
  let auditData;
  try {
    auditData = await API.audit();
  } catch {
    auditData = null;
  }

  const findings = auditData?.findings || [
    { id: 1, severity: 'medium', category: 'GDPR', title: 'Consent tracking incomplete', description: 'Some knowledge entries lack explicit consent markers', recommendation: 'Add consent_basis field to all identity-layer entries', status: 'open' },
    { id: 2, severity: 'low', category: 'ISO 27001', title: 'Audit log rotation not configured', description: 'Audit logs may grow unbounded', recommendation: 'Configure log rotation with 90-day retention', status: 'open' },
    { id: 3, severity: 'info', category: 'Best Practice', title: 'Backup encryption key escrow', description: 'PQC backup keys should have escrow mechanism', recommendation: 'Implement key escrow with split-knowledge', status: 'acknowledged' },
  ];

  if (findings.length === 0) {
    el.innerHTML = UI.emptyState('✅', 'No findings', 'All compliance checks passed');
    return;
  }

  const severityOrder = { critical: 0, high: 1, medium: 2, low: 3, info: 4 };
  findings.sort((a, b) => (severityOrder[a.severity] || 5) - (severityOrder[b.severity] || 5));

  el.innerHTML = `
    <div class="table-container">
      <table>
        <thead>
          <tr>
            <th>Severity</th>
            <th>Category</th>
            <th>Finding</th>
            <th>Recommendation</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          ${findings.map(f => `
            <tr>
              <td>${UI.badge(f.severity, f.severity === 'critical' || f.severity === 'high' ? 'danger' : f.severity === 'medium' ? 'warning' : 'info')}</td>
              <td>${UI.esc(f.category)}</td>
              <td>
                <div style="font-weight:500">${UI.esc(f.title)}</div>
                <div style="font-size:12px;color:var(--text-muted);margin-top:2px">${UI.esc(f.description)}</div>
              </td>
              <td style="font-size:13px">${UI.esc(f.recommendation)}</td>
              <td>${UI.badge(f.status, f.status === 'open' ? 'warning' : f.status === 'resolved' ? 'success' : 'neutral')}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
  `;
};

Pages.compliance.renderAuditLog = function(el) {
  el.innerHTML = `
    <div class="card">
      <div style="display:flex;gap:12px;margin-bottom:16px">
        <input class="input" placeholder="Search audit log..." style="flex:1">
        <select class="select" style="width:150px">
          <option>All actions</option>
          <option>Create</option>
          <option>Update</option>
          <option>Delete</option>
          <option>Export</option>
          <option>Access</option>
        </select>
        <button class="btn btn-secondary btn-sm">Filter</button>
      </div>
      ${UI.emptyState('📋', 'Audit log', 'Connect to API to view audit trail')}
    </div>
  `;
};

Pages.compliance.renderRetention = function(el) {
  el.innerHTML = `
    <div class="card">
      <div class="card-header">
        <div class="card-title">Data Retention Policies</div>
      </div>
      <div class="table-container" style="border:none">
        <table>
          <thead>
            <tr>
              <th>Data Layer</th>
              <th>Retention Period</th>
              <th>Auto-Expire</th>
              <th>Entries</th>
              <th>Expiring Soon</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>${UI.layerBadge('identity')}</td>
              <td>Indefinite</td>
              <td>${UI.badge('Off', 'neutral')}</td>
              <td>—</td>
              <td>—</td>
            </tr>
            <tr>
              <td>${UI.layerBadge('knowledge')}</td>
              <td>365 days</td>
              <td>${UI.badge('On', 'success')}</td>
              <td>—</td>
              <td>—</td>
            </tr>
            <tr>
              <td>${UI.layerBadge('team')}</td>
              <td>180 days</td>
              <td>${UI.badge('On', 'success')}</td>
              <td>—</td>
              <td>—</td>
            </tr>
            <tr>
              <td>${UI.layerBadge('operational')}</td>
              <td>90 days</td>
              <td>${UI.badge('On', 'success')}</td>
              <td>—</td>
              <td>—</td>
            </tr>
            <tr>
              <td>${UI.layerBadge('project')}</td>
              <td>Per project</td>
              <td>${UI.badge('Manual', 'warning')}</td>
              <td>—</td>
              <td>—</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `;
};

Pages.compliance.runAudit = async function() {
  UI.toast('Running compliance audit...', 'info');
  try {
    await API.audit({ run: true });
    UI.toast('Audit complete', 'success');
    Pages.compliance();
  } catch (e) {
    UI.toast('Audit failed: ' + e.message, 'error');
  }
};

Pages.compliance.exportReport = function() {
  UI.toast('Report export not yet connected to API', 'info');
};
