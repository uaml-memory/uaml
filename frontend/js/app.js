/**
 * UAML Dashboard — Router & App Shell
 */

const App = {
  currentPage: null,

  pages: {
    dashboard: { title: 'Dashboard', icon: '🏠', render: () => Pages.dashboard() },
    knowledge: { title: 'Knowledge', icon: '🧠', render: () => Pages.knowledge() },
    tasks:     { title: 'Tasks',     icon: '✅', render: () => Pages.tasks() },
    graph:     { title: 'Graph',     icon: '🔗', render: () => Pages.graph() },
    timeline:  { title: 'Timeline',  icon: '📊', render: () => Pages.timeline() },
    compliance:{ title: 'Compliance',icon: '🔐', render: () => Pages.compliance() },
    export:    { title: 'Export',    icon: '📦', render: () => Pages.exportImport() },
    settings:  { title: 'Settings',  icon: '⚙️', render: () => Pages.settings() },
  },

  init() {
    this.renderShell();
    this.bindEvents();
    // Route from hash or default to dashboard
    const hash = location.hash.slice(1) || 'dashboard';
    this.navigate(hash);
  },

  renderShell() {
    document.getElementById('app').innerHTML = `
      <div class="app">
        <aside class="sidebar" id="sidebar">
          <div class="sidebar-header">
            <div class="sidebar-logo">
              <span class="logo-icon">🧠</span>
              <span>UAML</span>
            </div>
            <button class="sidebar-toggle" id="sidebar-toggle" title="Toggle sidebar">☰</button>
          </div>
          <nav class="sidebar-nav">
            <div class="nav-section">
              <div class="nav-section-title">Overview</div>
              ${this.navItem('dashboard')}
            </div>
            <div class="nav-section">
              <div class="nav-section-title">Data</div>
              ${this.navItem('knowledge')}
              ${this.navItem('tasks')}
              ${this.navItem('graph')}
              ${this.navItem('timeline')}
            </div>
            <div class="nav-section">
              <div class="nav-section-title">System</div>
              ${this.navItem('compliance')}
              ${this.navItem('export')}
              ${this.navItem('settings')}
            </div>
          </nav>
          <div class="sidebar-footer">
            <div style="font-size:11px;color:var(--text-muted)">UAML v0.4.0</div>
          </div>
        </aside>
        <main class="main">
          <header class="main-header" id="main-header">
            <h1 id="page-title">Dashboard</h1>
            <div class="header-actions" id="header-actions"></div>
          </header>
          <div class="main-content" id="main-content">
          </div>
        </main>
      </div>
    `;
  },

  navItem(key) {
    const p = this.pages[key];
    return `<a class="nav-item" data-page="${key}" href="#${key}">
      <span class="nav-icon">${p.icon}</span>
      <span class="nav-label">${p.title}</span>
    </a>`;
  },

  bindEvents() {
    // Sidebar toggle
    document.getElementById('sidebar-toggle').addEventListener('click', () => {
      document.getElementById('sidebar').classList.toggle('collapsed');
    });

    // Hash navigation
    window.addEventListener('hashchange', () => {
      this.navigate(location.hash.slice(1));
    });

    // Nav clicks
    document.querySelector('.sidebar-nav').addEventListener('click', (e) => {
      const item = e.target.closest('.nav-item');
      if (item) {
        e.preventDefault();
        const page = item.dataset.page;
        location.hash = page;
      }
    });

    // Theme toggle via keyboard
    document.addEventListener('keydown', (e) => {
      if (e.ctrlKey && e.key === 't') {
        e.preventDefault();
        const theme = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
        document.documentElement.dataset.theme = theme;
        localStorage.setItem('uaml-theme', theme);
      }
    });

    // Restore theme
    const saved = localStorage.getItem('uaml-theme');
    if (saved) document.documentElement.dataset.theme = saved;
  },

  async navigate(page) {
    if (!this.pages[page]) page = 'dashboard';
    this.currentPage = page;

    // Update active nav
    document.querySelectorAll('.nav-item').forEach(el => {
      el.classList.toggle('active', el.dataset.page === page);
    });

    // Update title
    document.getElementById('page-title').textContent = this.pages[page].title;

    // Render page
    const content = document.getElementById('main-content');
    content.innerHTML = `<div style="display:flex;justify-content:center;padding:48px">${UI.spinner()}</div>`;

    try {
      await this.pages[page].render();
    } catch (e) {
      content.innerHTML = `
        <div class="card" style="text-align:center;padding:48px">
          <div style="font-size:48px;margin-bottom:16px">⚠️</div>
          <h3 style="margin-bottom:8px">Error loading page</h3>
          <p style="color:var(--text-muted)">${UI.esc(e.message)}</p>
          <br>
          <button class="btn btn-primary" onclick="App.navigate('${page}')">Retry</button>
        </div>`;
    }
  },
};

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => App.init());
