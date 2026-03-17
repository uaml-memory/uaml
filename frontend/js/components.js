/**
 * UAML Dashboard — Shared UI Components
 */

const UI = {
  // Toast notifications
  toast(message, type = 'info') {
    let container = document.querySelector('.toast-container');
    if (!container) {
      container = document.createElement('div');
      container.className = 'toast-container';
      document.body.appendChild(container);
    }
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    const icons = { success: '✅', error: '❌', info: 'ℹ️' };
    toast.innerHTML = `<span>${icons[type] || 'ℹ️'}</span> ${this.esc(message)}`;
    container.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateX(100%)';
      setTimeout(() => toast.remove(), 300);
    }, 4000);
  },

  // Stat card
  statCard(icon, label, value, subtitle, colorClass = 'primary') {
    return `
      <div class="card">
        <div class="stat-card">
          <div class="card-icon ${colorClass}">${icon}</div>
          <div class="stat-content">
            <div class="card-title">${this.esc(label)}</div>
            <div class="card-value">${this.esc(String(value))}</div>
            <div class="card-subtitle">${this.esc(subtitle || '')}</div>
          </div>
        </div>
      </div>`;
  },

  // Badge
  badge(text, type = 'neutral') {
    return `<span class="badge badge-${type}">${this.esc(text)}</span>`;
  },

  // Layer badge
  layerBadge(layer) {
    return `<span class="layer-badge layer-${layer}">${this.esc(layer)}</span>`;
  },

  // Status badge
  statusBadge(status) {
    const map = {
      pending: 'warning', in_progress: 'info', active: 'info',
      done: 'success', completed: 'success',
      failed: 'danger', error: 'danger',
    };
    return this.badge(status, map[status] || 'neutral');
  },

  // Empty state
  emptyState(icon, title, subtitle) {
    return `
      <div class="empty-state">
        <div class="empty-icon">${icon}</div>
        <h3>${this.esc(title)}</h3>
        <p>${this.esc(subtitle || '')}</p>
      </div>`;
  },

  // Loading skeleton
  skeleton(height = 20, width = '100%') {
    return `<div class="skeleton" style="height:${height}px;width:${typeof width === 'number' ? width + 'px' : width}"></div>`;
  },

  // Spinner
  spinner() {
    return '<div class="spinner"></div>';
  },

  // Progress bar
  progressBar(percent, color = 'primary') {
    return `
      <div class="progress-bar">
        <div class="progress-fill ${color}" style="width:${Math.min(100, Math.max(0, percent))}%"></div>
      </div>`;
  },

  // Compliance ring (SVG)
  complianceRing(score, size = 120) {
    const r = (size - 12) / 2;
    const c = Math.PI * 2 * r;
    const offset = c * (1 - score / 100);
    const color = score >= 80 ? 'var(--color-success)' : score >= 50 ? 'var(--color-warning)' : 'var(--color-danger)';
    return `
      <div class="compliance-ring" style="width:${size}px;height:${size}px">
        <svg width="${size}" height="${size}">
          <circle cx="${size/2}" cy="${size/2}" r="${r}" fill="none" stroke="var(--border)" stroke-width="8"/>
          <circle cx="${size/2}" cy="${size/2}" r="${r}" fill="none" stroke="${color}" stroke-width="8"
            stroke-dasharray="${c}" stroke-dashoffset="${offset}" stroke-linecap="round"/>
        </svg>
        <div class="score-text" style="color:${color}">${score}%</div>
      </div>`;
  },

  // Relative time
  timeAgo(ts) {
    if (!ts) return '—';
    const d = new Date(ts);
    const now = Date.now();
    const diff = Math.floor((now - d.getTime()) / 1000);
    if (diff < 60) return 'just now';
    if (diff < 3600) return `${Math.floor(diff/60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff/3600)}h ago`;
    if (diff < 604800) return `${Math.floor(diff/86400)}d ago`;
    return d.toLocaleDateString();
  },

  // Escape HTML
  esc(s) {
    if (s == null) return '';
    const el = document.createElement('span');
    el.textContent = String(s);
    return el.innerHTML;
  },

  // Modal open/close
  openModal(id) {
    document.getElementById(id)?.classList.add('active');
  },

  closeModal(id) {
    document.getElementById(id)?.classList.remove('active');
  },

  // Format number
  num(n) {
    if (n == null) return '0';
    return Number(n).toLocaleString();
  },
};
