/* UAML Dashboard — Main JavaScript */

// ─── i18n Engine ─────────────────────────────────────────
const LANGUAGES = {
    en: { flag: '🇬🇧', name: 'English' },
    cs: { flag: '🇨🇿', name: 'Čeština' },
    sk: { flag: '🇸🇰', name: 'Slovenčina' },
    pl: { flag: '🇵🇱', name: 'Polski' },
    fr: { flag: '🇫🇷', name: 'Français' },
    es: { flag: '🇪🇸', name: 'Español' },
};

let i18n = {};
let currentLang = localStorage.getItem('uaml-lang') || 'en';

function t(key, fallback) {
    const keys = key.split('.');
    let val = i18n;
    for (const k of keys) {
        if (val && typeof val === 'object' && k in val) val = val[k];
        else return fallback || key;
    }
    return typeof val === 'string' ? val : (fallback || key);
}

async function loadLanguage(lang) {
    try {
        const resp = await fetch(`/static/i18n/${lang}.json`);
        if (resp.ok) {
            i18n = await resp.json();
            currentLang = lang;
            localStorage.setItem('uaml-lang', lang);
            applyTranslations();
        }
    } catch (e) {
        console.error('i18n load error:', e);
    }
}

function applyTranslations() {
    // Update nav links — preserve emoji prefix
    const NAV_EMOJI = {
        dashboard: '📊', knowledge: '📚', tasks: '✅', graph: '🔗',
        timeline: '📅', projects: '📂', infrastructure: '🖥️', team: '👥',
        compliance: '🔐', export: '📦', settings: '⚙️'
    };
    document.querySelectorAll('.nav-link').forEach(link => {
        const page = link.getAttribute('data-page');
        if (page && i18n.nav && i18n.nav[page]) {
            const emoji = NAV_EMOJI[page] || '';
            link.textContent = emoji + ' ' + i18n.nav[page];
        }
    });
    // Update footer
    const footer = document.querySelector('.nav-footer');
    if (footer && i18n.common) {
        const dot = footer.querySelector('.status-dot');
        if (dot) footer.innerHTML = '';
        if (dot) footer.appendChild(dot);
        footer.appendChild(document.createTextNode(' ' + t('common.api_connected')));
    }
    // Update all elements with data-i18n
    document.querySelectorAll('[data-i18n]').forEach(el => {
        const key = el.getAttribute('data-i18n');
        el.textContent = t(key);
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
        el.placeholder = t(el.getAttribute('data-i18n-placeholder'));
    });
    // Update language selector display
    const langBtn = document.getElementById('lang-current');
    if (langBtn) langBtn.textContent = LANGUAGES[currentLang]?.flag + ' ' + LANGUAGES[currentLang]?.name;
}

function renderLangSwitcher() {
    const container = document.getElementById('lang-switcher');
    if (!container) return;
    container.innerHTML = `
        <button id="lang-current" class="btn btn-sm" onclick="toggleLangMenu()" style="width:100%;">
            ${LANGUAGES[currentLang]?.flag} ${LANGUAGES[currentLang]?.name}
        </button>
        <div id="lang-menu" style="display:none; position:absolute; bottom:100%; left:0; right:0; background:var(--bg-card); border:1px solid var(--border); border-radius:6px; z-index:300;">
            ${Object.entries(LANGUAGES).map(([code, l]) =>
                `<a href="#" class="nav-link" style="padding:8px 12px; font-size:13px;" onclick="setLang('${code}'); return false;">${l.flag} ${l.name}</a>`
            ).join('')}
        </div>
    `;
}

function toggleLangMenu() {
    const menu = document.getElementById('lang-menu');
    if (menu) menu.style.display = menu.style.display === 'none' ? 'block' : 'none';
}

function setLang(lang) {
    loadLanguage(lang);
    const menu = document.getElementById('lang-menu');
    if (menu) menu.style.display = 'none';
}

// ─── Active Nav ──────────────────────────────────────────
document.querySelectorAll('.nav-link').forEach(link => {
    if (link.getAttribute('href') === window.location.pathname) {
        link.classList.add('active');
    }
});

// ─── Utilities ───────────────────────────────────────────
function formatBytes(bytes) {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return (bytes / Math.pow(k, i)).toFixed(1) + ' ' + sizes[i];
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatTime(ts) {
    if (!ts) return '-';
    try {
        const d = new Date(ts.replace(' ', 'T'));
        if (isNaN(d.getTime())) return ts;
        const now = new Date();
        const diff = now - d;
        if (diff < 60000) return 'just now';
        if (diff < 3600000) return `${Math.floor(diff/60000)}m ago`;
        if (diff < 86400000) return `${Math.floor(diff/3600000)}h ago`;
        if (diff < 604800000) return `${Math.floor(diff/86400000)}d ago`;
        return d.toLocaleDateString();
    } catch { return ts; }
}

// ─── Health Check ────────────────────────────────────────
async function checkHealth() {
    try {
        const resp = await fetch('/api/health');
        if (resp.ok) document.querySelector('.nav-footer .status-dot')?.classList.add('green');
    } catch {
        const dot = document.querySelector('.nav-footer .status-dot');
        if (dot) { dot.classList.remove('green'); dot.classList.add('red'); }
    }
}

// ─── Sidebar Identity ────────────────────────────────────
async function loadSidebarIdentity() {
    try {
        const sys = await fetch('/api/system').then(r => r.json());
        const agentEl = document.getElementById('sid-agent');
        const machineEl = document.getElementById('sid-machine');
        const modelEl = document.getElementById('sid-model');
        if (agentEl) agentEl.innerHTML = `🤖 <strong>${escapeHtml(sys.agent?.name || 'UAML Agent')}</strong>`;
        if (machineEl) {
            const m = sys.machine || {};
            const hostname = typeof m === 'string' ? m : (m.hostname || '?');
            const os = m.os || '';
            machineEl.textContent = '🖥️ ' + hostname + (os ? ' • ' + os.split(' ')[0] : '');
        }
        if (modelEl) {
            if (sys.agent?.model && sys.agent.model !== 'not configured') {
                modelEl.textContent = '⚡ ' + sys.agent.model;
            } else {
                modelEl.textContent = '📦 UAML v' + (sys.versions?.uaml || '?');
            }
        }
        const dbEl = document.getElementById('sid-db');
        if (dbEl && sys.database?.path) {
            dbEl.textContent = '💾 ' + sys.database.path;
            dbEl.title = sys.database.path + ' (' + formatBytes(sys.database.size_bytes || 0) + ')';
        }
    } catch(e) { console.warn('Identity load:', e); }
}

// ─── Top Bar Info ────────────────────────────────────────
async function loadTopBarInfo() {
    try {
        const sys = await fetch('/api/system').then(r => r.json());
        const agentEl = document.getElementById('tb-agent');
        const machineEl = document.getElementById('tb-machine');
        const versionEl = document.getElementById('tb-version');
        if (agentEl) {
            const name = sys.agent?.name || 'UAML Agent';
            agentEl.innerHTML = '🤖 <strong>' + escapeHtml(name) + '</strong>';
        }
        if (machineEl) {
            const m = sys.machine || {};
            const hostname = typeof m === 'string' ? m : (m.hostname || '?');
            machineEl.textContent = '🖥️ ' + hostname;
        }
        if (versionEl) {
            versionEl.textContent = 'v' + (sys.versions?.uaml || '?');
        }
    } catch(e) { console.warn('Top bar load:', e); }
}

// ─── Init ────────────────────────────────────────────────
checkHealth();
setInterval(checkHealth, 30000);
renderLangSwitcher();
loadLanguage(currentLang);
loadSidebarIdentity();
loadTopBarInfo();

// Auto-refresh dashboard data every 60s
setInterval(() => {
    if (typeof loadDashboard === 'function') loadDashboard();
    if (typeof loadSystemInfo === 'function') loadSystemInfo();
}, 60000);
