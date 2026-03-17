/**
 * UAML Dashboard — Home / Overview Page
 */

Pages.dashboard = async function() {
  const content = document.getElementById('main-content');

  // Header actions
  document.getElementById('header-actions').innerHTML = `
    <button class="btn btn-secondary btn-sm" onclick="Pages.dashboard()">↻ Refresh</button>
    <button class="btn btn-ghost btn-sm" onclick="App.navigate('settings')">⚙️</button>
  `;

  // Load stats
  let stats, health, layers;
  try {
    [stats, health, layers] = await Promise.all([
      API.stats(),
      API.health(),
      API.layers().catch(() => null),
    ]);
  } catch (e) {
    content.innerHTML = `
      <div style="padding:48px;text-align:center">
        <div style="font-size:64px;margin-bottom:24px">🔌</div>
        <h2 style="margin-bottom:12px">API Server Not Running</h2>
        <p style="color:var(--text-muted);margin-bottom:24px">
          Start the UAML API server to connect the dashboard.
        </p>
        <code style="background:var(--bg-surface-hover);padding:12px 20px;border-radius:var(--radius-md);font-family:var(--font-mono);font-size:13px;display:inline-block">
          uaml serve --port 8780
        </code>
      </div>`;
    return;
  }

  const apiOk = health && health.status === 'ok';

  content.innerHTML = `
    <!-- Stats Row -->
    <div class="page-grid grid-4" style="margin-bottom:24px">
      ${UI.statCard('🧠', 'Knowledge', UI.num(stats.knowledge_count || 0), `${UI.num(stats.topics || 0)} topics`, 'info')}
      ${UI.statCard('✅', 'Tasks', UI.num(stats.task_count || 0),
        `${UI.num(stats.tasks_done || 0)} done, ${UI.num(stats.tasks_pending || 0)} pending`, 'success')}
      ${UI.statCard('🔗', 'Relations', UI.num(stats.relation_count || 0), 'knowledge links', 'primary')}
      ${UI.statCard('📦', 'Artifacts', UI.num(stats.artifact_count || 0), 'files & outputs', 'warning')}
    </div>

    <div class="page-grid grid-2-1">
      <!-- Recent Activity -->
      <div class="card">
        <div class="card-header">
          <div class="card-title">Recent Activity</div>
          <button class="btn btn-ghost btn-sm" onclick="App.navigate('timeline')">View all →</button>
        </div>
        <div id="recent-activity">
          ${UI.skeleton(200)}
        </div>
      </div>

      <!-- Right Column -->
      <div style="display:flex;flex-direction:column;gap:20px">
        <!-- System Health -->
        <div class="card">
          <div class="card-header">
            <div class="card-title">System Health</div>
          </div>
          <div style="display:flex;flex-direction:column;gap:12px">
            <div style="display:flex;justify-content:space-between;align-items:center">
              <span style="font-size:13px">API Server</span>
              ${UI.badge(apiOk ? 'Online' : 'Offline', apiOk ? 'success' : 'danger')}
            </div>
            <div style="display:flex;justify-content:space-between;align-items:center">
              <span style="font-size:13px">Database</span>
              ${UI.badge(stats.db_size ? 'OK' : 'Unknown', stats.db_size ? 'success' : 'neutral')}
            </div>
            ${stats.db_size ? `
            <div style="display:flex;justify-content:space-between;align-items:center">
              <span style="font-size:13px">DB Size</span>
              <span style="font-size:13px;color:var(--text-muted)">${formatBytes(stats.db_size)}</span>
            </div>` : ''}
            ${stats.last_backup ? `
            <div style="display:flex;justify-content:space-between;align-items:center">
              <span style="font-size:13px">Last Backup</span>
              <span style="font-size:13px;color:var(--text-muted)">${UI.timeAgo(stats.last_backup)}</span>
            </div>` : ''}
          </div>
        </div>

        <!-- Quick Actions -->
        <div class="card">
          <div class="card-header">
            <div class="card-title">Quick Actions</div>
          </div>
          <div style="display:flex;flex-direction:column;gap:8px">
            <button class="btn btn-secondary" onclick="App.navigate('knowledge')" style="justify-content:flex-start">
              🧠 Browse Knowledge
            </button>
            <button class="btn btn-secondary" onclick="App.navigate('tasks')" style="justify-content:flex-start">
              ✅ Manage Tasks
            </button>
            <button class="btn btn-secondary" onclick="App.navigate('export')" style="justify-content:flex-start">
              📦 Export Data
            </button>
            <button class="btn btn-secondary" onclick="App.navigate('compliance')" style="justify-content:flex-start">
              🔐 Run Audit
            </button>
          </div>
        </div>

        <!-- Data Layers -->
        ${layers ? `
        <div class="card">
          <div class="card-header">
            <div class="card-title">Data Layers</div>
          </div>
          <div style="display:flex;flex-direction:column;gap:8px">
            ${(layers.layers || []).map(l => `
              <div style="display:flex;justify-content:space-between;align-items:center">
                ${UI.layerBadge(l.layer)}
                <span style="font-size:13px;color:var(--text-muted)">${UI.num(l.count)} entries</span>
              </div>
            `).join('')}
          </div>
        </div>` : ''}
      </div>
    </div>
  `;

  // Load recent activity
  loadRecentActivity();
};

async function loadRecentActivity() {
  const el = document.getElementById('recent-activity');
  if (!el) return;

  try {
    const timeline = await API.timeline({ limit: 10 });
    if (!timeline.events || timeline.events.length === 0) {
      el.innerHTML = UI.emptyState('📭', 'No activity yet', 'Start adding knowledge or tasks');
      return;
    }

    el.innerHTML = timeline.events.map(e => `
      <div class="activity-item">
        <div class="activity-dot ${e.type || 'knowledge'}"></div>
        <div>
          <div class="activity-text">${UI.esc(e.summary || e.title || e.content?.substring(0, 100) || '—')}</div>
          <div class="activity-time">${UI.timeAgo(e.timestamp)} · ${UI.esc(e.type || 'event')}</div>
        </div>
      </div>
    `).join('');
  } catch {
    el.innerHTML = '<div style="color:var(--text-muted);font-size:13px;padding:12px">Could not load activity</div>';
  }
}

function formatBytes(bytes) {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  let i = 0;
  let size = bytes;
  while (size >= 1024 && i < units.length - 1) { size /= 1024; i++; }
  return `${size.toFixed(1)} ${units[i]}`;
}
