/**
 * UAML Dashboard — Knowledge Browser Page
 */

Pages.knowledge = async function() {
  const content = document.getElementById('main-content');

  document.getElementById('header-actions').innerHTML = `
    <button class="btn btn-primary btn-sm" onclick="Pages.knowledge.showCreate()">+ New Entry</button>
  `;

  content.innerHTML = `
    <!-- Search & Filters -->
    <div class="card" style="margin-bottom:20px">
      <div style="display:flex;gap:12px;flex-wrap:wrap">
        <div style="flex:1;min-width:200px">
          <div class="search-input">
            <input class="input" id="k-search" placeholder="Search knowledge..." type="text">
          </div>
        </div>
        <select class="select" id="k-layer" style="width:150px">
          <option value="">All Layers</option>
          <option value="identity">Identity</option>
          <option value="knowledge">Knowledge</option>
          <option value="team">Team</option>
          <option value="operational">Operational</option>
          <option value="project">Project</option>
        </select>
        <input class="input" id="k-topic" placeholder="Topic..." style="width:150px">
        <input class="input" id="k-project" placeholder="Project..." style="width:150px">
        <button class="btn btn-primary" onclick="Pages.knowledge.search()">Search</button>
      </div>
    </div>

    <!-- Results -->
    <div id="k-results">
      ${UI.skeleton(300)}
    </div>

    <!-- Create Modal -->
    <div class="modal-overlay" id="modal-create-knowledge">
      <div class="modal">
        <div class="modal-header">
          <h2>New Knowledge Entry</h2>
          <button class="btn btn-ghost btn-sm" onclick="UI.closeModal('modal-create-knowledge')">✕</button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label class="form-label">Content *</label>
            <textarea class="textarea" id="k-new-content" rows="4" placeholder="What did you learn?"></textarea>
          </div>
          <div class="form-row">
            <div class="form-group">
              <label class="form-label">Topic</label>
              <input class="input" id="k-new-topic" placeholder="e.g. architecture">
            </div>
            <div class="form-group">
              <label class="form-label">Layer</label>
              <select class="select" id="k-new-layer">
                <option value="knowledge">Knowledge</option>
                <option value="identity">Identity</option>
                <option value="team">Team</option>
                <option value="operational">Operational</option>
                <option value="project">Project</option>
              </select>
            </div>
          </div>
          <div class="form-row">
            <div class="form-group">
              <label class="form-label">Project</label>
              <input class="input" id="k-new-project" placeholder="Optional">
            </div>
            <div class="form-group">
              <label class="form-label">Confidence</label>
              <input class="input" id="k-new-confidence" type="number" min="0" max="1" step="0.1" value="0.8">
            </div>
          </div>
          <div class="form-group">
            <label class="form-label">Source</label>
            <input class="input" id="k-new-source" placeholder="Where did this come from?">
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-secondary" onclick="UI.closeModal('modal-create-knowledge')">Cancel</button>
          <button class="btn btn-primary" onclick="Pages.knowledge.create()">Create</button>
        </div>
      </div>
    </div>
  `;

  // Search on Enter
  document.getElementById('k-search').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') Pages.knowledge.search();
  });

  // Initial load
  Pages.knowledge.search();
};

Pages.knowledge.search = async function() {
  const el = document.getElementById('k-results');
  el.innerHTML = `<div style="display:flex;justify-content:center;padding:24px">${UI.spinner()}</div>`;

  const params = {};
  const q = document.getElementById('k-search').value.trim();
  const layer = document.getElementById('k-layer').value;
  const topic = document.getElementById('k-topic').value.trim();
  const project = document.getElementById('k-project').value.trim();

  if (q) params.query = q;
  if (layer) params.layer = layer;
  if (topic) params.topic = topic;
  if (project) params.project = project;
  if (!params.query) params.limit = 50;

  try {
    const data = await API.searchKnowledge(params);
    const entries = data.results || data.entries || data || [];

    if (entries.length === 0) {
      el.innerHTML = UI.emptyState('🔍', 'No results', 'Try different search terms or filters');
      return;
    }

    el.innerHTML = `
      <div style="margin-bottom:12px;font-size:13px;color:var(--text-muted)">
        ${entries.length} result${entries.length !== 1 ? 's' : ''}
      </div>
      <div style="display:flex;flex-direction:column;gap:12px">
        ${entries.map(e => `
          <div class="card" style="padding:16px;cursor:pointer" onclick="Pages.knowledge.detail(${e.id})">
            <div style="display:flex;align-items:flex-start;gap:12px">
              <div style="flex:1">
                <div style="font-size:14px;margin-bottom:8px">${UI.esc(truncate(e.content, 200))}</div>
                <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
                  ${e.layer ? UI.layerBadge(e.layer) : ''}
                  ${e.topic ? UI.badge(e.topic, 'info') : ''}
                  ${e.project ? UI.badge(e.project, 'primary') : ''}
                  ${e.confidence != null ? `<span style="font-size:11px;color:var(--text-muted)">⭐ ${(e.confidence * 100).toFixed(0)}%</span>` : ''}
                  <span style="font-size:11px;color:var(--text-muted)">${UI.timeAgo(e.created_at || e.timestamp)}</span>
                </div>
              </div>
              <button class="btn btn-ghost btn-sm" onclick="event.stopPropagation();Pages.knowledge.deleteEntry(${e.id})" title="Delete">🗑️</button>
            </div>
          </div>
        `).join('')}
      </div>`;
  } catch (e) {
    el.innerHTML = `<div class="card" style="color:var(--color-danger);padding:24px">Error: ${UI.esc(e.message)}</div>`;
  }
};

Pages.knowledge.detail = async function(id) {
  try {
    const entry = await API.getKnowledge(id);
    const e = entry.entry || entry;

    const content = document.getElementById('main-content');
    content.innerHTML = `
      <div style="margin-bottom:16px">
        <button class="btn btn-ghost btn-sm" onclick="Pages.knowledge()">← Back</button>
      </div>
      <div class="card">
        <div class="card-header">
          <div style="display:flex;gap:8px;align-items:center">
            ${e.layer ? UI.layerBadge(e.layer) : ''}
            ${e.topic ? UI.badge(e.topic, 'info') : ''}
            ${e.project ? UI.badge(e.project, 'primary') : ''}
          </div>
          <span style="font-size:11px;color:var(--text-muted)">ID: ${e.id}</span>
        </div>
        <div style="font-size:15px;line-height:1.7;margin-bottom:20px;white-space:pre-wrap">${UI.esc(e.content)}</div>
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;font-size:13px;color:var(--text-secondary)">
          ${e.source ? `<div><strong>Source:</strong> ${UI.esc(e.source)}</div>` : ''}
          ${e.agent ? `<div><strong>Agent:</strong> ${UI.esc(e.agent)}</div>` : ''}
          ${e.confidence != null ? `<div><strong>Confidence:</strong> ${(e.confidence * 100).toFixed(0)}%</div>` : ''}
          ${e.created_at ? `<div><strong>Created:</strong> ${new Date(e.created_at).toLocaleString()}</div>` : ''}
          ${e.client ? `<div><strong>Client:</strong> ${UI.esc(e.client)}</div>` : ''}
        </div>
      </div>`;
  } catch (e) {
    UI.toast('Failed to load entry: ' + e.message, 'error');
  }
};

Pages.knowledge.showCreate = function() {
  UI.openModal('modal-create-knowledge');
};

Pages.knowledge.create = async function() {
  const content = document.getElementById('k-new-content').value.trim();
  if (!content) { UI.toast('Content is required', 'error'); return; }

  try {
    await API.createKnowledge({
      content,
      topic: document.getElementById('k-new-topic').value.trim() || undefined,
      layer: document.getElementById('k-new-layer').value,
      project: document.getElementById('k-new-project').value.trim() || undefined,
      confidence: parseFloat(document.getElementById('k-new-confidence').value) || 0.8,
      source: document.getElementById('k-new-source').value.trim() || undefined,
    });
    UI.closeModal('modal-create-knowledge');
    UI.toast('Knowledge entry created', 'success');
    Pages.knowledge.search();
  } catch (e) {
    UI.toast('Failed: ' + e.message, 'error');
  }
};

Pages.knowledge.deleteEntry = async function(id) {
  if (!confirm('Delete this knowledge entry?')) return;
  try {
    await API.deleteKnowledge(id);
    UI.toast('Entry deleted', 'success');
    Pages.knowledge.search();
  } catch (e) {
    UI.toast('Failed: ' + e.message, 'error');
  }
};

function truncate(s, max) {
  if (!s) return '';
  return s.length > max ? s.substring(0, max) + '…' : s;
}
