/**
 * UAML Dashboard — Graph Explorer (Cyril)
 * Placeholder — will integrate neovis.js for Neo4j visualization
 */

Pages.graph = async function() {
  const content = document.getElementById('main-content');
  document.getElementById('header-actions').innerHTML = `
    <button class="btn btn-secondary btn-sm" onclick="Pages.graph()">↻ Refresh</button>
  `;

  content.innerHTML = `
    <div class="card" style="text-align:center;padding:64px">
      <div style="font-size:64px;margin-bottom:16px">🔗</div>
      <h2 style="margin-bottom:8px">Graph Explorer</h2>
      <p style="color:var(--text-muted);margin-bottom:24px">
        Interactive Neo4j knowledge graph visualization.<br>
        Coming in next build — will use neovis.js.
      </p>
      <div style="display:flex;gap:12px;justify-content:center">
        <div class="card" style="padding:16px;text-align:center;min-width:120px">
          <div class="card-value" style="font-size:24px">—</div>
          <div class="card-subtitle">Nodes</div>
        </div>
        <div class="card" style="padding:16px;text-align:center;min-width:120px">
          <div class="card-value" style="font-size:24px">—</div>
          <div class="card-subtitle">Relationships</div>
        </div>
        <div class="card" style="padding:16px;text-align:center;min-width:120px">
          <div class="card-value" style="font-size:24px">—</div>
          <div class="card-subtitle">Types</div>
        </div>
      </div>
    </div>
  `;
};
