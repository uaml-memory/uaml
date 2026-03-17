/**
 * UAML Dashboard — Export / Import / Backup Page
 */

Pages.exportImport = async function() {
  const content = document.getElementById('main-content');

  document.getElementById('header-actions').innerHTML = '';

  content.innerHTML = `
    <div class="tabs">
      <div class="tab active" data-tab="export" onclick="Pages.exportImport.switchTab('export')">Export</div>
      <div class="tab" data-tab="import" onclick="Pages.exportImport.switchTab('import')">Import</div>
      <div class="tab" data-tab="backup" onclick="Pages.exportImport.switchTab('backup')">Backup</div>
    </div>
    <div id="export-content"></div>
  `;

  Pages.exportImport.switchTab('export');
};

Pages.exportImport.switchTab = function(tab) {
  document.querySelectorAll('.tabs .tab').forEach(t =>
    t.classList.toggle('active', t.dataset.tab === tab)
  );
  const el = document.getElementById('export-content');

  switch (tab) {
    case 'export': Pages.exportImport.renderExport(el); break;
    case 'import': Pages.exportImport.renderImport(el); break;
    case 'backup': Pages.exportImport.renderBackup(el); break;
  }
};

Pages.exportImport.renderExport = function(el) {
  el.innerHTML = `
    <div class="page-grid grid-2">
      <!-- Export Wizard -->
      <div class="card">
        <div class="card-header">
          <div class="card-title">Export Data</div>
        </div>
        <div class="form-group">
          <label class="form-label">Data Type</label>
          <select class="select" id="exp-type">
            <option value="all">All Data</option>
            <option value="knowledge">Knowledge Only</option>
            <option value="tasks">Tasks Only</option>
            <option value="artifacts">Artifacts Only</option>
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">Layer Filter</label>
          <select class="select" id="exp-layer">
            <option value="">All Layers</option>
            <option value="identity">Identity</option>
            <option value="knowledge">Knowledge</option>
            <option value="team">Team</option>
            <option value="operational">Operational</option>
            <option value="project">Project</option>
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">Project Filter</label>
          <input class="input" id="exp-project" placeholder="All projects">
        </div>
        <div class="form-group">
          <label class="form-label">Client Filter</label>
          <input class="input" id="exp-client" placeholder="All clients">
        </div>
        <div class="form-group">
          <label class="form-label">Format</label>
          <select class="select" id="exp-format">
            <option value="json">JSON</option>
            <option value="csv">CSV</option>
            <option value="sqlite">SQLite Database</option>
          </select>
        </div>
        <div class="form-group">
          <label style="display:flex;align-items:center;gap:8px;font-size:13px;cursor:pointer">
            <input type="checkbox" id="exp-encrypt"> Encrypt with PQC (ML-KEM-768)
          </label>
        </div>
        <button class="btn btn-primary" onclick="Pages.exportImport.doExport()" style="width:100%">
          📦 Export
        </button>
      </div>

      <!-- Export History -->
      <div class="card">
        <div class="card-header">
          <div class="card-title">Recent Exports</div>
        </div>
        ${UI.emptyState('📦', 'No exports yet', 'Run your first export to see history')}
      </div>
    </div>
  `;
};

Pages.exportImport.renderImport = function(el) {
  el.innerHTML = `
    <div class="card" style="max-width:600px">
      <div class="card-header">
        <div class="card-title">Import Data</div>
      </div>
      <div style="border:2px dashed var(--border);border-radius:var(--radius-lg);padding:48px;text-align:center;margin-bottom:20px;cursor:pointer"
           onclick="document.getElementById('import-file').click()"
           id="drop-zone">
        <div style="font-size:48px;margin-bottom:12px">📁</div>
        <div style="font-size:15px;font-weight:500;margin-bottom:4px">Drop file here or click to browse</div>
        <div style="font-size:13px;color:var(--text-muted)">Supports JSON, CSV, SQLite</div>
        <input type="file" id="import-file" accept=".json,.csv,.db,.sqlite" style="display:none"
               onchange="Pages.exportImport.previewImport(this)">
      </div>

      <div id="import-preview"></div>

      <div class="form-group">
        <label style="display:flex;align-items:center;gap:8px;font-size:13px;cursor:pointer">
          <input type="checkbox" id="import-merge" checked> Merge with existing data (skip duplicates)
        </label>
      </div>

      <button class="btn btn-primary" id="import-btn" disabled style="width:100%">
        📥 Import
      </button>
    </div>
  `;
};

Pages.exportImport.renderBackup = function(el) {
  el.innerHTML = `
    <div class="page-grid grid-2">
      <!-- Create Backup -->
      <div class="card">
        <div class="card-header">
          <div class="card-title">Create Backup</div>
        </div>
        <p style="font-size:13px;color:var(--text-secondary);margin-bottom:20px">
          Create a full backup of the UAML database with optional PQC encryption.
        </p>
        <div class="form-group">
          <label style="display:flex;align-items:center;gap:8px;font-size:13px;cursor:pointer">
            <input type="checkbox" id="backup-encrypt" checked> Encrypt with PQC (ML-KEM-768 + AES-256-GCM)
          </label>
        </div>
        <div class="form-group">
          <label style="display:flex;align-items:center;gap:8px;font-size:13px;cursor:pointer">
            <input type="checkbox" id="backup-verify" checked> Verify after creation
          </label>
        </div>
        <button class="btn btn-primary" onclick="Pages.exportImport.doBackup()" style="width:100%">
          💾 Create Backup
        </button>
      </div>

      <!-- Backup History -->
      <div class="card">
        <div class="card-header">
          <div class="card-title">Backup History</div>
        </div>
        ${UI.emptyState('💾', 'No backups recorded', 'Connect to API to view backup history')}
      </div>
    </div>

    <!-- Backup Schedule -->
    <div class="card" style="margin-top:20px">
      <div class="card-header">
        <div class="card-title">Backup Schedule</div>
      </div>
      <div class="table-container" style="border:none">
        <table>
          <thead>
            <tr><th>Schedule</th><th>Destination</th><th>Encryption</th><th>Retention</th><th>Status</th></tr>
          </thead>
          <tbody>
            <tr>
              <td>Daily 03:00</td>
              <td>Local + Git</td>
              <td>${UI.badge('PQC', 'success')}</td>
              <td>14 days</td>
              <td>${UI.badge('Active', 'success')}</td>
            </tr>
            <tr>
              <td>Weekly Sunday 04:00</td>
              <td>Wedos 1TB</td>
              <td>${UI.badge('PQC', 'success')}</td>
              <td>90 days</td>
              <td>${UI.badge('Active', 'success')}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `;
};

Pages.exportImport.doExport = async function() {
  const type = document.getElementById('exp-type').value;
  const layer = document.getElementById('exp-layer').value;
  const project = document.getElementById('exp-project').value.trim();
  const client = document.getElementById('exp-client').value.trim();
  const format = document.getElementById('exp-format').value;
  const encrypt = document.getElementById('exp-encrypt').checked;

  UI.toast('Starting export...', 'info');
  try {
    const result = await API.exportData({ type, layer, project, client, format, encrypt });
    UI.toast(`Export complete: ${result.filename || 'download ready'}`, 'success');
  } catch (e) {
    UI.toast('Export failed: ' + e.message, 'error');
  }
};

Pages.exportImport.doBackup = async function() {
  UI.toast('Creating backup...', 'info');
  try {
    const result = await API.backup();
    UI.toast(`Backup created: ${result.filename || 'success'}`, 'success');
  } catch (e) {
    UI.toast('Backup failed: ' + e.message, 'error');
  }
};

Pages.exportImport.previewImport = function(input) {
  const file = input.files[0];
  if (!file) return;

  const preview = document.getElementById('import-preview');
  preview.innerHTML = `
    <div style="background:var(--bg-surface-hover);padding:12px;border-radius:var(--radius-md);margin-bottom:16px;font-size:13px">
      <strong>${UI.esc(file.name)}</strong> (${formatBytes(file.size)})
    </div>
  `;
  document.getElementById('import-btn').disabled = false;
};

function formatBytes(bytes) {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  let i = 0, size = bytes;
  while (size >= 1024 && i < units.length - 1) { size /= 1024; i++; }
  return `${size.toFixed(1)} ${units[i]}`;
}
