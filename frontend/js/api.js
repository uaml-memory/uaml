/**
 * UAML REST API Client
 * Communicates with uaml.api.server endpoints
 */

const API = {
  baseUrl: '',  // Same origin, or set to http://host:8780

  async request(method, path, body = null) {
    const opts = {
      method,
      headers: { 'Content-Type': 'application/json' },
    };
    if (body) opts.body = JSON.stringify(body);

    try {
      const res = await fetch(`${this.baseUrl}${path}`, opts);
      if (!res.ok) {
        const err = await res.json().catch(() => ({ error: res.statusText }));
        throw new Error(err.error || `HTTP ${res.status}`);
      }
      return await res.json();
    } catch (e) {
      if (e.message === 'Failed to fetch') {
        throw new Error('API server unreachable. Is UAML running?');
      }
      throw e;
    }
  },

  // Health
  health() { return this.request('GET', '/api/v1/health'); },
  stats() { return this.request('GET', '/api/v1/stats'); },
  layers() { return this.request('GET', '/api/v1/layers'); },

  // Knowledge
  searchKnowledge(params = {}) {
    const qs = new URLSearchParams(params).toString();
    return this.request('GET', `/api/v1/knowledge${qs ? '?' + qs : ''}`);
  },
  getKnowledge(id) { return this.request('GET', `/api/v1/knowledge/${id}`); },
  createKnowledge(data) { return this.request('POST', '/api/v1/knowledge', data); },
  deleteKnowledge(id) { return this.request('DELETE', `/api/v1/knowledge/${id}`); },

  // Tasks
  listTasks(params = {}) {
    const qs = new URLSearchParams(params).toString();
    return this.request('GET', `/api/v1/tasks${qs ? '?' + qs : ''}`);
  },
  getTask(id) { return this.request('GET', `/api/v1/tasks/${id}`); },
  createTask(data) { return this.request('POST', '/api/v1/tasks', data); },
  updateTask(id, data) { return this.request('PUT', `/api/v1/tasks/${id}`, data); },
  deleteTask(id) { return this.request('DELETE', `/api/v1/tasks/${id}`); },

  // Artifacts
  listArtifacts(params = {}) {
    const qs = new URLSearchParams(params).toString();
    return this.request('GET', `/api/v1/artifacts${qs ? '?' + qs : ''}`);
  },
  createArtifact(data) { return this.request('POST', '/api/v1/artifacts', data); },

  // Graph
  getGraph(entityId) { return this.request('GET', `/api/v1/graph/${entityId}`); },

  // Timeline
  timeline(params = {}) {
    const qs = new URLSearchParams(params).toString();
    return this.request('GET', `/api/v1/timeline${qs ? '?' + qs : ''}`);
  },

  // Export / Backup
  exportData(filters) { return this.request('POST', '/api/v1/export', filters); },
  backup() { return this.request('POST', '/api/v1/backup'); },

  // Compliance
  audit(params = {}) {
    const qs = new URLSearchParams(params).toString();
    return this.request('GET', `/api/v1/compliance/audit${qs ? '?' + qs : ''}`);
  },
};
