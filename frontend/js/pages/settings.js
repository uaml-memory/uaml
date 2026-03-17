/**
 * UAML Dashboard — Settings Page
 */

Pages.settings = async function() {
  const content = document.getElementById('main-content');
  document.getElementById('header-actions').innerHTML = '';

  let health;
  try { health = await API.health(); } catch { health = null; }

  content.innerHTML = `
    <div class="tabs">
      <div class="tab active" data-tab="general" onclick="Pages.settings.switchTab('general')">General</div>
      <div class="tab" data-tab="api" onclick="Pages.settings.switchTab('api')">API</div>
      <div class="tab" data-tab="agents" onclick="Pages.settings.switchTab('agents')">Agents</div>
      <div class="tab" data-tab="database" onclick="Pages.settings.switchTab('database')">Database</div>
      <div class="tab" data-tab="about" onclick="Pages.settings.switchTab('about')">About</div>
    </div>
    <div id="settings-content"></div>
  `;

  Pages.settings.switchTab('general');
};

Pages.settings.switchTab = function(tab) {
  document.querySelectorAll('.tabs .tab').forEach(t =>
    t.classList.toggle('active', t.dataset.tab === tab)
  );
  const el = document.getElementById('settings-content');

  switch (tab) {
    case 'general': Pages.settings.renderGeneral(el); break;
    case 'api': Pages.settings.renderAPI(el); break;
    case 'agents': Pages.settings.renderAgents(el); break;
    case 'database': Pages.settings.renderDatabase(el); break;
    case 'about': Pages.settings.renderAbout(el); break;
  }
};

Pages.settings.renderGeneral = function(el) {
  const theme = document.documentElement.dataset.theme || 'dark';
  el.innerHTML = `
    <div class="card" style="max-width:600px">
      <div class="card-header">
        <div class="card-title">Appearance</div>
      </div>
      <div class="form-group">
        <label class="form-label">Theme</label>
        <select class="select" id="set-theme" onchange="Pages.settings.setTheme(this.value)">
          <option value="dark" ${theme === 'dark' ? 'selected' : ''}>🌙 Dark</option>
          <option value="light" ${theme === 'light' ? 'selected' : ''}>☀️ Light</option>
        </select>
      </div>
      <div style="font-size:12px;color:var(--text-muted);margin-top:8px">
        Tip: Press <kbd style="background:var(--bg-surface-hover);padding:2px 6px;border-radius:3px;font-family:var(--font-mono)">Ctrl+T</kbd> to toggle theme
      </div>
    </div>

    <div class="card" style="max-width:600px;margin-top:20px">
      <div class="card-header">
        <div class="card-title">Dashboard</div>
      </div>
      <div class="form-group">
        <label class="form-label">Refresh Interval</label>
        <select class="select">
          <option>Manual</option>
          <option>Every 30 seconds</option>
          <option>Every minute</option>
          <option>Every 5 minutes</option>
        </select>
      </div>
      <div class="form-group">
        <label class="form-label">Default page</label>
        <select class="select">
          <option value="dashboard">Dashboard</option>
          <option value="knowledge">Knowledge</option>
          <option value="tasks">Tasks</option>
        </select>
      </div>
    </div>
  `;
};

Pages.settings.renderAPI = function(el) {
  el.innerHTML = `
    <div class="card" style="max-width:600px">
      <div class="card-header">
        <div class="card-title">API Configuration</div>
      </div>
      <div class="form-group">
        <label class="form-label">API Base URL</label>
        <input class="input" id="set-api-url" value="${API.baseUrl || window.location.origin}" placeholder="http://localhost:8780">
      </div>
      <div class="form-group">
        <label class="form-label">Connection Status</label>
        <div id="api-status" style="font-size:13px">${UI.spinner()}</div>
      </div>
      <div style="display:flex;gap:8px">
        <button class="btn btn-primary" onclick="Pages.settings.testAPI()">Test Connection</button>
        <button class="btn btn-secondary" onclick="Pages.settings.saveAPI()">Save</button>
      </div>
    </div>
  `;
  Pages.settings.testAPI();
};

Pages.settings.renderAgents = function(el) {
  el.innerHTML = `
    <div class="card" style="max-width:600px">
      <div class="card-header">
        <div class="card-title">Registered Agents</div>
      </div>
      <div class="table-container" style="border:none">
        <table>
          <thead>
            <tr><th>Agent</th><th>Role</th><th>Key</th><th>Status</th></tr>
          </thead>
          <tbody>
            <tr>
              <td><strong>Pepa2</strong></td>
              <td>Admin / Coordinator</td>
              <td style="font-family:var(--font-mono);font-size:12px">ed25519:pepa2…</td>
              <td>${UI.badge('Active', 'success')}</td>
            </tr>
            <tr>
              <td><strong>Cyril</strong></td>
              <td>Developer</td>
              <td style="font-family:var(--font-mono);font-size:12px">ed25519:cyril…</td>
              <td>${UI.badge('Active', 'success')}</td>
            </tr>
            <tr>
              <td><strong>Pepa-PC</strong></td>
              <td>Infrastructure</td>
              <td style="font-family:var(--font-mono);font-size:12px">ed25519:pepa-pc…</td>
              <td>${UI.badge('Active', 'success')}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `;
};

Pages.settings.renderDatabase = function(el) {
  el.innerHTML = `
    <div class="card" style="max-width:600px">
      <div class="card-header">
        <div class="card-title">Database</div>
      </div>
      <div style="display:flex;flex-direction:column;gap:12px;font-size:13px" id="db-info">
        ${UI.skeleton(120)}
      </div>
      <div style="display:flex;gap:8px;margin-top:20px">
        <button class="btn btn-secondary" onclick="Pages.settings.dbVacuum()">🧹 Vacuum</button>
        <button class="btn btn-secondary" onclick="Pages.settings.dbIntegrity()">✅ Integrity Check</button>
      </div>
    </div>
  `;

  // Load DB stats
  API.stats().then(stats => {
    document.getElementById('db-info').innerHTML = `
      <div style="display:flex;justify-content:space-between"><span>Size</span><span>${formatBytes(stats.db_size || 0)}</span></div>
      <div style="display:flex;justify-content:space-between"><span>Knowledge entries</span><span>${UI.num(stats.knowledge_count || 0)}</span></div>
      <div style="display:flex;justify-content:space-between"><span>Tasks</span><span>${UI.num(stats.task_count || 0)}</span></div>
      <div style="display:flex;justify-content:space-between"><span>Relations</span><span>${UI.num(stats.relation_count || 0)}</span></div>
      <div style="display:flex;justify-content:space-between"><span>Artifacts</span><span>${UI.num(stats.artifact_count || 0)}</span></div>
    `;
  }).catch(() => {
    document.getElementById('db-info').innerHTML = '<div style="color:var(--text-muted)">Could not load database stats</div>';
  });
};

Pages.settings.renderAbout = function(el) {
  el.innerHTML = `
    <div class="card" style="max-width:600px;text-align:center;padding:48px">
      <div style="font-size:64px;margin-bottom:16px">🧠</div>
      <h2 style="margin-bottom:4px">UAML</h2>
      <div style="color:var(--text-muted);margin-bottom:24px">Universal Agent Memory Layer</div>
      <div style="font-size:13px;color:var(--text-secondary);margin-bottom:24px">
        Persistent, temporal, ethical memory for AI agents.<br>
        Zero external dependencies. Platform-agnostic.
      </div>
      <div style="display:flex;flex-direction:column;gap:8px;font-size:13px;text-align:left;max-width:300px;margin:0 auto">
        <div style="display:flex;justify-content:space-between">
          <span>Version</span><span style="font-family:var(--font-mono)">0.4.0</span>
        </div>
        <div style="display:flex;justify-content:space-between">
          <span>Python</span><span style="font-family:var(--font-mono)">≥ 3.10</span>
        </div>
        <div style="display:flex;justify-content:space-between">
          <span>License</span><span>Proprietary</span>
        </div>
        <div style="display:flex;justify-content:space-between">
          <span>Tests</span><span style="color:var(--color-success)">408/408 ✅</span>
        </div>
      </div>
    </div>
  `;
};

Pages.settings.setTheme = function(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem('uaml-theme', theme);
};

Pages.settings.testAPI = async function() {
  const el = document.getElementById('api-status');
  if (!el) return;
  el.innerHTML = UI.spinner();

  try {
    const health = await API.health();
    el.innerHTML = `${UI.badge('Connected', 'success')} <span style="margin-left:8px;color:var(--text-muted)">${health.timestamp || ''}</span>`;
  } catch (e) {
    el.innerHTML = `${UI.badge('Disconnected', 'danger')} <span style="margin-left:8px;color:var(--text-muted)">${e.message}</span>`;
  }
};

Pages.settings.saveAPI = function() {
  const url = document.getElementById('set-api-url')?.value?.trim();
  if (url) {
    API.baseUrl = url === window.location.origin ? '' : url;
    localStorage.setItem('uaml-api-url', API.baseUrl);
    UI.toast('API URL saved', 'success');
  }
};

Pages.settings.dbVacuum = function() {
  UI.toast('Database vacuum not yet connected to API', 'info');
};

Pages.settings.dbIntegrity = function() {
  UI.toast('Integrity check not yet connected to API', 'info');
};

function formatBytes(bytes) {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  let i = 0, size = bytes;
  while (size >= 1024 && i < units.length - 1) { size /= 1024; i++; }
  return `${size.toFixed(1)} ${units[i]}`;
}
