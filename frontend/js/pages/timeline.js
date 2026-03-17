/**
 * UAML Dashboard — Timeline Page (Cyril)
 * Placeholder — chronological event feed
 */

Pages.timeline = async function() {
  const content = document.getElementById('main-content');
  document.getElementById('header-actions').innerHTML = `
    <button class="btn btn-secondary btn-sm" onclick="Pages.timeline()">↻ Refresh</button>
  `;

  content.innerHTML = `
    <!-- Filters -->
    <div style="display:flex;gap:12px;margin-bottom:20px;flex-wrap:wrap">
      <select class="select" style="width:150px">
        <option>All events</option>
        <option>Knowledge</option>
        <option>Tasks</option>
        <option>Audit</option>
      </select>
      <input class="input" type="date" style="width:160px">
      <input class="input" type="date" style="width:160px">
      <button class="btn btn-secondary btn-sm">Filter</button>
    </div>

    <div id="timeline-feed">${UI.skeleton(400)}</div>
  `;

  // Load timeline
  try {
    const data = await API.timeline({ limit: 50 });
    const events = data.events || [];
    const el = document.getElementById('timeline-feed');

    if (events.length === 0) {
      el.innerHTML = UI.emptyState('📊', 'No events', 'Activity will appear here as you use UAML');
      return;
    }

    el.innerHTML = `<div style="display:flex;flex-direction:column;gap:0">
      ${events.map(e => `
        <div class="activity-item">
          <div class="activity-dot ${e.type || 'knowledge'}"></div>
          <div style="flex:1">
            <div class="activity-text">${UI.esc(e.summary || e.title || e.content?.substring(0, 150) || '—')}</div>
            <div class="activity-time">
              ${UI.timeAgo(e.timestamp)}
              ${e.type ? ` · ${UI.esc(e.type)}` : ''}
              ${e.agent ? ` · ${UI.esc(e.agent)}` : ''}
              ${e.project ? ` · 📁 ${UI.esc(e.project)}` : ''}
            </div>
          </div>
        </div>
      `).join('')}
    </div>`;
  } catch (e) {
    document.getElementById('timeline-feed').innerHTML =
      `<div class="card" style="color:var(--color-danger)">${UI.esc(e.message)}</div>`;
  }
};
