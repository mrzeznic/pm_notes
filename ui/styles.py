CUSTOM_CSS = """
body {
    background-color: #090d13;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    margin: 0;
    padding: 0;
}

/* Let Quasar page containers grow naturally */
.q-page-container {
    min-height: 100vh;
}

.q-page {
    display: flex !important;
    flex-direction: column !important;
    min-height: 100%;
}

/* Force NiceGUI refreshable wrapper divs to stack correctly */
.main-content-area > div,
nicegui-refreshable {
    display: flex !important;
    flex-direction: column !important;
    flex-grow: 1 !important;
    width: 100% !important;
}

.sidebar-active {
    background-color: #1f6feb !important;
    color: #ffffff !important;
}

.task-card {
    transition: all 0.15s cubic-bezier(0.4, 0, 0.2, 1);
}

.task-card:hover {
    border-color: #58a6ff !important;
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
}

.kanban-column {
    background-color: #11161f;
    border: 1px solid #21262d;
    border-radius: 10px;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    min-height: 0;
}

.kanban-header {
    border-bottom: 1px solid #21262d;
    padding: 8px 12px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.08em;
    flex-shrink: 0;
}

/* Kanban grid must fill its parent */
.kanban-grid {
    flex: 1 1 0% !important;
    min-height: 0 !important;
    height: 100% !important;
}

/* Kanban columns: ensure scroll area fills */
.kanban-column .q-scrollarea {
    flex: 1 1 0% !important;
    min-height: 0 !important;
}

.text-standard {
    font-size: 13.5px !important;
    line-height: 1.5;
}

.text-header-section {
    font-size: 11px !important;
    font-weight: 700;
    letter-spacing: 0.08em;
}

/* Task list scroll area must fill available space */
.list-scroll-area {
    flex: 1 1 0% !important;
    min-height: 0 !important;
    height: 100% !important;
}

.list-scroll-area .q-scrollarea {
    height: 100% !important;
}

.list-scroll-area .q-scrollarea__container {
    height: 100% !important;
}

::-webkit-scrollbar {
    width: 6px;
    height: 6px;
}

::-webkit-scrollbar-track {
    background: transparent;
}

::-webkit-scrollbar-thumb {
    background: #21262d;
    border-radius: 4px;
}

::-webkit-scrollbar-thumb:hover {
    background: #58a6ff;
}

.diff-add {
    background-color: rgba(46, 160, 67, 0.15);
    color: #3fb950;
    border-left: 3px solid #2ea043;
    padding-left: 6px;
}

.diff-del {
    background-color: rgba(248, 81, 73, 0.15);
    color: #f85149;
    border-left: 3px solid #da3633;
    padding-left: 6px;
    text-decoration: line-through;
}

.diff-same {
    color: #8b949e;
    padding-left: 9px;
}
"""
