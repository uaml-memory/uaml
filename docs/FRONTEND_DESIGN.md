# UAML Dashboard — Frontend Design Document

**Version:** 1.0  
**Date:** 2026-03-08  
**Authors:** Pepa2 (Settings, Tasks, Compliance, Export) + Cyril (Dashboard, Knowledge, Graph, Timeline)

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    UAML Dashboard                        │
│  ┌──────────┐  ┌──────────────────────────────────────┐ │
│  │ Sidebar  │  │           Content Area                │ │
│  │          │  │                                       │ │
│  │ 🏠 Home  │  │  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐   │ │
│  │ 🧠 Know  │  │  │Card │ │Card │ │Card │ │Card │   │ │
│  │ ✅ Tasks │  │  └─────┘ └─────┘ └─────┘ └─────┘   │ │
│  │ 🔗 Graph │  │                                       │ │
│  │ 📊 Time  │  │  ┌─────────────────────────────────┐ │ │
│  │ 🔐 Audit │  │  │     Main Content Block          │ │ │
│  │ 📦 Export│  │  │                                  │ │ │
│  │ ⚙️ Set   │  │  └─────────────────────────────────┘ │ │
│  └──────────┘  └──────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

## Pages

### 1. 🏠 Dashboard (Home)
- **Summary cards**: Knowledge count, Task stats, Compliance score, Neo4j node/rel counts
- **Recent activity**: Last 10 knowledge entries + task changes
- **Quick actions**: New knowledge, New task, Run backup, Export
- **System health**: API status, DB size, last backup time
- **Links**: Quick navigation to all sections

### 2. 🧠 Knowledge Browser
- **Search bar** with full-text search
- **Filters**: Layer (identity/knowledge/team/operational/project), Topic, Project, Client, Confidence
- **Results**: Card grid or table view (toggle)
- **Detail panel**: Full entry with metadata, relations, source links, edit/delete
- **Create**: Modal for adding new knowledge entries

### 3. ✅ Tasks (Kanban)
- **3-column kanban**: Pending → In Progress → Done
- **Drag & drop** between columns
- **Filters**: Project, Assigned agent, Priority, Client
- **Task card**: Title, status, assigned, due date, project badge
- **Quick create**: Inline task creation
- **Bulk operations**: Select multiple → move/delete/export

### 4. 🔗 Graph Explorer
- **Neo4j visualization** via neovis.js
- **Entity search**: Find node by name/type
- **Interactive**: Click node → show details + neighbors
- **Filters**: Node type, relationship type, depth
- **Layout**: Force-directed, hierarchical, or radial

### 5. 📊 Timeline
- **Chronological feed**: All events (knowledge, tasks, audit) on one timeline
- **Filters**: Event type, date range, project, agent
- **Zoom**: Day / Week / Month view
- **Color coding**: Green=knowledge, Blue=tasks, Red=audit, Gray=system

### 6. 🔐 Compliance & Audit
- **Compliance score**: Overall + per-category (GDPR, ISO 27001)
- **Findings table**: Issue, severity, recommendation, status
- **Audit log**: Who did what when (filterable)
- **Reports**: Generate PDF/JSON compliance report
- **Data retention**: Expired entries, retention policy status

### 7. 📦 Export / Import
- **Export wizard**: Select data type → filters → format (JSON/CSV/SQLite)
- **Import**: Upload JSON/CSV → preview → confirm
- **Backup management**: List backups, create new, restore, schedule
- **PQC encryption**: Toggle encryption for exports, key management

### 8. ⚙️ Settings
- **API configuration**: Host, port, auth
- **Agent management**: Registered agents, keys
- **Database**: DB path, size, vacuum, integrity check
- **Theme**: Dark / Light / Auto
- **About**: Version, license, links

## Design System

### Colors (Dark Theme — Primary)
- Background: `#0f1117` (deep dark)
- Surface: `#1a1d27` (cards, panels)
- Surface hover: `#252836`
- Border: `#2d3148`
- Primary: `#6366f1` (indigo)
- Primary hover: `#818cf8`
- Success: `#22c55e`
- Warning: `#f59e0b`
- Danger: `#ef4444`
- Text: `#e2e8f0`
- Text muted: `#94a3b8`

### Typography
- Font: `Inter, -apple-system, sans-serif`
- Headings: 600 weight
- Body: 400 weight
- Monospace: `JetBrains Mono, monospace`

### Components
- Cards with subtle border + shadow
- Rounded corners (8px cards, 6px buttons, 4px inputs)
- Sidebar: Fixed, 240px wide, collapsible to 60px (icons only)
- Modals for create/edit forms
- Toast notifications for actions
- Loading skeletons

### Responsive
- Desktop: Sidebar + full content
- Tablet: Collapsed sidebar + full content
- Mobile: Bottom nav + stacked cards

## File Structure

```
frontend/
├── index.html          # Shell + router
├── css/
│   ├── variables.css   # Design tokens
│   ├── layout.css      # Grid, sidebar, content
│   ├── components.css  # Cards, buttons, modals, forms
│   └── pages.css       # Page-specific styles
├── js/
│   ├── app.js          # Router + init
│   ├── api.js          # REST API client
│   ├── components.js   # Shared UI components
│   ├── pages/
│   │   ├── dashboard.js
│   │   ├── knowledge.js
│   │   ├── tasks.js
│   │   ├── graph.js
│   │   ├── timeline.js
│   │   ├── compliance.js
│   │   ├── export.js
│   │   └── settings.js
│   └── utils.js        # Helpers, formatters
└── assets/
    └── logo.svg
```

## API Dependencies

All pages consume `/api/v1/*` endpoints from `uaml.api.server`.
Frontend served as static files by the same server (or separate).

## Implementation Split

| Page | Owner | Priority |
|------|-------|----------|
| Layout + Router | Pepa2 (skeleton) | P0 |
| Dashboard Home | Cyril | P0 |
| Knowledge | Cyril | P0 |
| Tasks Kanban | Pepa2 | P0 |
| Graph | Cyril | P1 |
| Timeline | Cyril | P1 |
| Compliance | Pepa2 | P1 |
| Export/Import | Pepa2 | P1 |
| Settings | Pepa2 | P2 |

---
© 2026 GLG, a.s. All rights reserved. / Všechna práva vyhrazena.
License: Non-commercial use only. Commercial use requires a paid license from GLG, a.s.

