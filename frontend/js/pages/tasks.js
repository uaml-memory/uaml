/**
 * UAML Dashboard — Tasks Kanban Page
 */

Pages.tasks = async function() {
  const content = document.getElementById('main-content');

  document.getElementById('header-actions').innerHTML = `
    <button class="btn btn-primary btn-sm" onclick="Pages.tasks.showCreate()">+ New Task</button>
    <button class="btn btn-secondary btn-sm" onclick="Pages.tasks()">↻ Refresh</button>
  `;

  content.innerHTML = `
    <!-- Filters -->
    <div style="display:flex;gap:12px;margin-bottom:20px;flex-wrap:wrap">
      <input class="input" id="t-project" placeholder="Filter by project..." style="width:180px">
      <input class="input" id="t-assigned" placeholder="Assigned to..." style="width:150px">
      <button class="btn btn-secondary btn-sm" onclick="Pages.tasks.load()">Apply</button>
    </div>

    <!-- Kanban Board -->
    <div class="kanban" id="kanban-board">
      <div class="kanban-column" data-status="pending">
        <div class="kanban-column-header">
          <span>📋 Pending</span>
          <span class="count" id="count-pending">0</span>
        </div>
        <div class="kanban-cards" id="col-pending"></div>
      </div>
      <div class="kanban-column" data-status="in_progress">
        <div class="kanban-column-header">
          <span>🔧 In Progress</span>
          <span class="count" id="count-in_progress">0</span>
        </div>
        <div class="kanban-cards" id="col-in_progress"></div>
      </div>
      <div class="kanban-column" data-status="done">
        <div class="kanban-column-header">
          <span>✅ Done</span>
          <span class="count" id="count-done">0</span>
        </div>
        <div class="kanban-cards" id="col-done"></div>
      </div>
    </div>

    <!-- Create Modal -->
    <div class="modal-overlay" id="modal-create-task">
      <div class="modal">
        <div class="modal-header">
          <h2>New Task</h2>
          <button class="btn btn-ghost btn-sm" onclick="UI.closeModal('modal-create-task')">✕</button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label class="form-label">Title *</label>
            <input class="input" id="t-new-title" placeholder="What needs to be done?">
          </div>
          <div class="form-group">
            <label class="form-label">Description</label>
            <textarea class="textarea" id="t-new-desc" rows="3" placeholder="Details..."></textarea>
          </div>
          <div class="form-row">
            <div class="form-group">
              <label class="form-label">Project</label>
              <input class="input" id="t-new-project" placeholder="Optional">
            </div>
            <div class="form-group">
              <label class="form-label">Assigned To</label>
              <input class="input" id="t-new-assigned" placeholder="Agent name">
            </div>
          </div>
          <div class="form-row">
            <div class="form-group">
              <label class="form-label">Priority</label>
              <select class="select" id="t-new-priority">
                <option value="medium">Medium</option>
                <option value="low">Low</option>
                <option value="high">High</option>
                <option value="critical">Critical</option>
              </select>
            </div>
            <div class="form-group">
              <label class="form-label">Due Date</label>
              <input class="input" id="t-new-due" type="date">
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-secondary" onclick="UI.closeModal('modal-create-task')">Cancel</button>
          <button class="btn btn-primary" onclick="Pages.tasks.create()">Create Task</button>
        </div>
      </div>
    </div>

    <!-- Edit Modal -->
    <div class="modal-overlay" id="modal-edit-task">
      <div class="modal">
        <div class="modal-header">
          <h2>Edit Task</h2>
          <button class="btn btn-ghost btn-sm" onclick="UI.closeModal('modal-edit-task')">✕</button>
        </div>
        <div class="modal-body" id="edit-task-body"></div>
        <div class="modal-footer">
          <button class="btn btn-danger btn-sm" id="edit-task-delete" style="margin-right:auto">Delete</button>
          <button class="btn btn-secondary" onclick="UI.closeModal('modal-edit-task')">Cancel</button>
          <button class="btn btn-primary" id="edit-task-save">Save</button>
        </div>
      </div>
    </div>
  `;

  // Init drag & drop
  Pages.tasks.initDragDrop();

  // Load tasks
  Pages.tasks.load();
};

Pages.tasks.load = async function() {
  const params = {};
  const project = document.getElementById('t-project')?.value?.trim();
  const assigned = document.getElementById('t-assigned')?.value?.trim();
  if (project) params.project = project;
  if (assigned) params.assigned = assigned;

  try {
    const data = await API.listTasks(params);
    const tasks = data.tasks || data || [];

    const groups = { pending: [], in_progress: [], done: [] };
    tasks.forEach(t => {
      const status = t.status || 'pending';
      if (groups[status]) groups[status].push(t);
      else groups.pending.push(t);
    });

    Object.entries(groups).forEach(([status, items]) => {
      const col = document.getElementById(`col-${status}`);
      const count = document.getElementById(`count-${status}`);
      if (count) count.textContent = items.length;

      if (!col) return;
      if (items.length === 0) {
        col.innerHTML = `<div style="text-align:center;padding:24px;color:var(--text-muted);font-size:13px">No tasks</div>`;
        return;
      }

      col.innerHTML = items.map(t => Pages.tasks.renderCard(t)).join('');
    });
  } catch (e) {
    UI.toast('Failed to load tasks: ' + e.message, 'error');
  }
};

Pages.tasks.renderCard = function(t) {
  const priorityColors = { critical: 'danger', high: 'warning', medium: 'info', low: 'neutral' };
  const pc = priorityColors[t.priority] || 'neutral';

  return `
    <div class="kanban-card" draggable="true" data-id="${t.id}" onclick="Pages.tasks.edit(${t.id})">
      <div class="kanban-card-title">${UI.esc(t.title || t.description?.substring(0, 60) || 'Untitled')}</div>
      <div class="kanban-card-meta">
        ${t.priority ? UI.badge(t.priority, pc) : ''}
        ${t.project ? `<span>📁 ${UI.esc(t.project)}</span>` : ''}
        ${t.assigned_to ? `<span>👤 ${UI.esc(t.assigned_to)}</span>` : ''}
      </div>
    </div>`;
};

Pages.tasks.initDragDrop = function() {
  const board = document.getElementById('kanban-board');
  if (!board) return;

  board.addEventListener('dragstart', (e) => {
    const card = e.target.closest('.kanban-card');
    if (!card) return;
    card.classList.add('dragging');
    e.dataTransfer.setData('text/plain', card.dataset.id);
  });

  board.addEventListener('dragend', (e) => {
    const card = e.target.closest('.kanban-card');
    if (card) card.classList.remove('dragging');
  });

  board.querySelectorAll('.kanban-cards').forEach(col => {
    col.addEventListener('dragover', (e) => {
      e.preventDefault();
      col.style.background = 'var(--bg-surface-hover)';
    });

    col.addEventListener('dragleave', () => {
      col.style.background = '';
    });

    col.addEventListener('drop', async (e) => {
      e.preventDefault();
      col.style.background = '';
      const taskId = e.dataTransfer.getData('text/plain');
      const newStatus = col.closest('.kanban-column').dataset.status;

      try {
        await API.updateTask(taskId, { status: newStatus });
        UI.toast(`Task moved to ${newStatus.replace('_', ' ')}`, 'success');
        Pages.tasks.load();
      } catch (err) {
        UI.toast('Failed to move task: ' + err.message, 'error');
      }
    });
  });
};

Pages.tasks.showCreate = function() {
  UI.openModal('modal-create-task');
};

Pages.tasks.create = async function() {
  const title = document.getElementById('t-new-title').value.trim();
  if (!title) { UI.toast('Title is required', 'error'); return; }

  try {
    await API.createTask({
      title,
      description: document.getElementById('t-new-desc').value.trim() || undefined,
      project: document.getElementById('t-new-project').value.trim() || undefined,
      assigned_to: document.getElementById('t-new-assigned').value.trim() || undefined,
      priority: document.getElementById('t-new-priority').value,
      due_date: document.getElementById('t-new-due').value || undefined,
      status: 'pending',
    });
    UI.closeModal('modal-create-task');
    UI.toast('Task created', 'success');
    Pages.tasks.load();
  } catch (e) {
    UI.toast('Failed: ' + e.message, 'error');
  }
};

Pages.tasks.edit = async function(id) {
  try {
    const data = await API.getTask(id);
    const t = data.task || data;

    document.getElementById('edit-task-body').innerHTML = `
      <input type="hidden" id="edit-task-id" value="${t.id}">
      <div class="form-group">
        <label class="form-label">Title</label>
        <input class="input" id="t-edit-title" value="${UI.esc(t.title || '')}">
      </div>
      <div class="form-group">
        <label class="form-label">Description</label>
        <textarea class="textarea" id="t-edit-desc" rows="3">${UI.esc(t.description || '')}</textarea>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label class="form-label">Status</label>
          <select class="select" id="t-edit-status">
            <option value="pending" ${t.status === 'pending' ? 'selected' : ''}>Pending</option>
            <option value="in_progress" ${t.status === 'in_progress' ? 'selected' : ''}>In Progress</option>
            <option value="done" ${t.status === 'done' ? 'selected' : ''}>Done</option>
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">Priority</label>
          <select class="select" id="t-edit-priority">
            <option value="low" ${t.priority === 'low' ? 'selected' : ''}>Low</option>
            <option value="medium" ${t.priority === 'medium' ? 'selected' : ''}>Medium</option>
            <option value="high" ${t.priority === 'high' ? 'selected' : ''}>High</option>
            <option value="critical" ${t.priority === 'critical' ? 'selected' : ''}>Critical</option>
          </select>
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label class="form-label">Project</label>
          <input class="input" id="t-edit-project" value="${UI.esc(t.project || '')}">
        </div>
        <div class="form-group">
          <label class="form-label">Assigned To</label>
          <input class="input" id="t-edit-assigned" value="${UI.esc(t.assigned_to || '')}">
        </div>
      </div>
    `;

    document.getElementById('edit-task-save').onclick = async () => {
      try {
        await API.updateTask(t.id, {
          title: document.getElementById('t-edit-title').value.trim(),
          description: document.getElementById('t-edit-desc').value.trim(),
          status: document.getElementById('t-edit-status').value,
          priority: document.getElementById('t-edit-priority').value,
          project: document.getElementById('t-edit-project').value.trim() || null,
          assigned_to: document.getElementById('t-edit-assigned').value.trim() || null,
        });
        UI.closeModal('modal-edit-task');
        UI.toast('Task updated', 'success');
        Pages.tasks.load();
      } catch (e) {
        UI.toast('Failed: ' + e.message, 'error');
      }
    };

    document.getElementById('edit-task-delete').onclick = async () => {
      if (!confirm('Delete this task?')) return;
      try {
        await API.deleteTask(t.id);
        UI.closeModal('modal-edit-task');
        UI.toast('Task deleted', 'success');
        Pages.tasks.load();
      } catch (e) {
        UI.toast('Failed: ' + e.message, 'error');
      }
    };

    UI.openModal('modal-edit-task');
  } catch (e) {
    UI.toast('Failed to load task: ' + e.message, 'error');
  }
};
