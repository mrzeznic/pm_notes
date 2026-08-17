import asyncio
import difflib
import re
from pathlib import Path
from typing import List, Optional

from nicegui import ui, app, core

from core.config import load_config, save_config, BASE_DIR, SYSTEM_LOG_FILE
from core.logger import AILogger
from models.task import Task, Project
from services.ai_engine import AIEngine
from services.markdown_parser import MarkdownParser
from services.project_service import ProjectService
from services.project_watcher import ProjectWatcher
from services.semantic_search import SemanticSearch
from ui.styles import CUSTOM_CSS, get_project_color

class WebTPM:
    def __init__(self):
        self.config = load_config()
        AILogger.setup(SYSTEM_LOG_FILE)

        self.active_idx = 0
        self.projects: List[Project] = []
        self.archived_projects: List[Project] = []
        self.watcher = ProjectWatcher(self.on_file_changed)

        # View and Filter State
        self.view_mode = 'kanban'  # 'list', 'kanban', 'timeline', 'raw'
        self.search_query = ""
        self.global_search = False
        self.semantic_mode = False
        self.filter_type = "all"  # "all", "p1", "in_progress", "blocked", "overdue"
        
        self.insights_content = ""
        self.daily_content = "No roadmap generated yet."
        self.standup_content = "No standup generated yet."
        self.refactor_content = "No refactor preview available."
        self.original_refactor_content = ""
        self.processing_status = ""
        self.project_summary = "Select a project to view its summary."
        
        self.ai_mode = "local"
        self.ai_cache = {}
        self.show_archived_p = False
        self.show_archived_t = False
        
        # Semantic Search Initialization
        self.semantic_search = SemanticSearch()
        
        # Connect logger to UI refresh
        AILogger.ui_refresh_callback = self._safe_refresh_logs

        self.refresh_portfolio()
        self.setup_ui()
        AILogger.log("TPM Enterprise Command Center Initialized", "success")

        # Startup background tasks
        app.on_startup(self.startup_sequence)

    def _safe_refresh_logs(self):
        """Safely refreshes the logs component across async event loop boundaries."""
        try:
            if core.loop:
                ui.timer(0, self.render_logs.refresh, once=True)
        except Exception:
            pass

    async def startup_sequence(self):
        """Generates initial summary on startup if valid project exists."""
        if self.projects and self.projects[0].name != "Empty_Portfolio":
            await self.update_project_summary()

    def get_all_projects(self) -> List[Project]:
        return self.projects + (self.archived_projects if self.show_archived_p else [])

    def get_active_project(self) -> Project:
        all_p = self.get_all_projects()
        if not all_p:
            return Project(name="Empty_Portfolio")
        if self.active_idx >= len(all_p):
            self.active_idx = 0
        
        active = all_p[self.active_idx]
        if active.path:
            self.watcher.watch(active.path.parent)
        return active

    def refresh_portfolio(self):
        root_path = Path(self.config["PROJECTS_ROOT"])
        self.projects, self.archived_projects = ProjectService.scan_projects(root_path, self.show_archived_p)
        AILogger.log(f"Discovery: {len(self.projects)} active projects in '{self.config['PROJECTS_ROOT']}'", "info")

    def parse_active_tasks(self) -> List[Task]:
        projects_to_parse = []
        if getattr(self, 'global_search', False):
            projects_to_parse = [p for p in self.projects if p.path and p.path.exists()]
        else:
            p = self.get_active_project()
            if p and p.path and p.path.exists():
                projects_to_parse = [p]

        raw_tasks = []
        for proj in projects_to_parse:
            try:
                content = proj.path.read_text(encoding='utf-8', errors='ignore')
                raw_tasks.extend(MarkdownParser.parse_tasks(content, self.show_archived_t, project_path=proj.path))
            except Exception as e:
                AILogger.log(f"Error parsing tasks for {proj.name}: {e}", "error")
        
        # Apply Semantic Search or Keyword Search
        filtered = []
        q = self.search_query.lower().strip()
        
        semantic_match_ids = []
        if q and getattr(self, 'semantic_mode', False):
            # Also ensure all current tasks are indexed before searching
            self.semantic_search.index_tasks(raw_tasks)
            semantic_match_ids = self.semantic_search.search(q)
            
        for t in raw_tasks:
            if q:
                if self.semantic_mode:
                    if t.id not in semantic_match_ids:
                        continue
                else:
                    if (q not in t.clean_text.lower() and q not in t.desc.lower() and q not in (t.blocked or "").lower() and q not in (t.dep or "").lower()):
                        continue
            if self.filter_type == "p1" and t.prio != 1:
                continue
            if self.filter_type == "in_progress" and t.kanban_status != "in_progress":
                continue
            if self.filter_type == "blocked" and not t.blocked:
                continue
            if self.filter_type == "overdue" and not t.overdue:
                continue
            filtered.append(t)
        return filtered

    async def switch_project_async(self, idx: int):
        self.active_idx = idx
        self.global_search = False
        await self.render_sidebar.refresh()
        await self.render_tasks_container.refresh()
        await self.render_project_summary.refresh()
        await self.update_project_summary()

    async def toggle_global_search(self):
        await self.render_sidebar.refresh()
        await self.render_tasks_container.refresh()

    def move_kanban_status(self, task: Task, direction: int):
        statuses = ["todo", "in_progress", "blocked", "done"]
        try:
            current_idx = statuses.index(task.kanban_status)
            new_idx = current_idx + direction
            if 0 <= new_idx < len(statuses):
                task.status_override = statuses[new_idx]
                task.is_done = (task.status_override == 'done')
                self.update_task_block(task, task.to_markdown_line())
        except ValueError:
            pass

    def toggle_task(self, task: Task, current_state: bool):
        path = task.project_path or self.get_active_project().path
        if not path or not path.exists():
            return
        lines = path.read_text(encoding='utf-8').splitlines()
        if not (0 <= task.line_start < len(lines)):
            return

        line = lines[task.line_start]
        is_done = bool(re.search(r'\[[xX]\]', line))
        status = "COMPLETED" if not is_done else "RE-OPENED"
        AILogger.log(f"Task {status}: {line[:35]}...", "info")

        if is_done:
            lines[task.line_start] = re.sub(r'\[[xX]\]', '[ ]', line, count=1)
        else:
            lines[task.line_start] = re.sub(r'\[\s\]', '[x]', line, count=1)

        ProjectService.atomic_write(project.path, "\n".join(lines) + "\n")
        self.refresh_portfolio()
        self.render_sidebar.refresh()
        self.render_tasks_container.refresh()

    def move_task(self, task: Task, direction: int):
        path = task.project_path or self.get_active_project().path
        if not path or not path.exists():
            return
        content = path.read_text(encoding='utf-8')
        lines = content.splitlines()
        tasks = MarkdownParser.parse_tasks(content, show_archived=self.config["SHOW_ARCHIVED"])
        
        # Sort by actual line index to find strictly contiguous tasks in file
        tasks.sort(key=lambda t: t.line_start)
        
        curr_idx = next((i for i, t in enumerate(tasks) if t.id == task.id), -1)
        if curr_idx == -1: return
        
        new_idx = curr_idx + direction
        if 0 <= new_idx < len(tasks):
            swap_task = tasks[new_idx]
            t1, t2 = (task, swap_task) if task.line_start < swap_task.line_start else (swap_task, task)
            
            b1 = lines[t1.line_start:t1.line_end]
            b2 = lines[t2.line_start:t2.line_end]
            
            # Reconstruct the text block containing both tasks and whatever is between them
            prefix = lines[:t1.line_start]
            between = lines[t1.line_end:t2.line_start]
            suffix = lines[t2.line_end:]
            
            # Swap them!
            new_lines = prefix + b2 + between + b1 + suffix
            
            ProjectService.atomic_write(project.path, "\n".join(new_lines) + "\n")
            self.refresh_portfolio()
            self.render_sidebar.refresh()
            self.render_tasks_container.refresh()

    def add_new_task(self):
        text = self.new_task_input.value.strip()
        project = self.get_active_project()
        if text and project.path:
            AILogger.log(f"Adding task to {project.name}: {text[:30]}...", "info")
            content = project.path.read_text(encoding='utf-8') if project.path.exists() else ""
            updated = MarkdownParser.add_task(content, text)
            ProjectService.atomic_write(project.path, updated)
            self.new_task_input.value = ""
            self.refresh_portfolio()
            self.render_sidebar.refresh()
            self.render_tasks_container.refresh()

    def archive_task(self, task: Task):
        project = self.get_active_project()
        if not project.path or not project.path.exists():
            return
        content = project.path.read_text(encoding='utf-8')
        updated, archived_line = MarkdownParser.archive_task(content, task.line_start, task.line_end)
        if archived_line:
            AILogger.log(f"Archived task: {archived_line[:30]}...", "info")
            ProjectService.atomic_write(project.path, updated)
            self.refresh_portfolio()
            self.render_sidebar.refresh()
            self.render_tasks_container.refresh()

    async def delete_task(self, task: Task, dialog_to_close=None):
        project = self.get_active_project()
        if not project.path or not project.path.exists():
            return
            
        with ui.dialog() as confirm_dialog, ui.card().classes('w-96 bg-gray-900 border border-red-900 p-4'):
            ui.label('Confirm Deletion').classes('text-lg font-bold text-red-500 mb-2')
            ui.label('Are you sure you want to permanently delete this task?').classes('text-sm text-gray-300 mb-4')
            with ui.row().classes('w-full justify-end gap-2'):
                ui.button('Cancel', on_click=confirm_dialog.close).props('flat color=gray')
                ui.button('Delete', on_click=lambda: confirm_dialog.submit('confirm')).props('color=red')
        
        if await confirm_dialog == 'confirm':
            content = project.path.read_text(encoding='utf-8')
            updated, deleted_line = MarkdownParser.delete_task(content, task.line_start, task.line_end)
            if deleted_line:
                ProjectService.create_backup(project.path)
                AILogger.log(f"Deleted task: {deleted_line[:30]}...", "info")
                ProjectService.atomic_write(project.path, updated)
                self.refresh_portfolio()
                self.render_sidebar.refresh()
                self.render_tasks_container.refresh()
            if dialog_to_close:
                dialog_to_close.submit(None)

    def archive_project(self, idx: Optional[int] = None):
        target_idx = idx if idx is not None else self.active_idx
        all_p = self.get_all_projects()
        if target_idx >= len(all_p):
            return
        project = all_p[target_idx]
        if project.name == "Empty_Portfolio" or project.is_archived:
            return

        AILogger.log(f"Archiving project '{project.name}'...", "info")
        root_path = Path(self.config["PROJECTS_ROOT"])
        if ProjectService.archive_project(project, root_path):
            ui.notify(f"Archived {project.name}", type="positive")
            self.active_idx = 0
            self.refresh_portfolio()
            self.render_sidebar.refresh()
            self.render_tasks_container.refresh()
            asyncio.create_task(self.update_project_summary())

    def unarchive_project(self, idx: int):
        all_p = self.get_all_projects()
        if idx >= len(all_p):
            return
        project = all_p[idx]
        if not project.is_archived:
            return

        root_path = Path(self.config["PROJECTS_ROOT"])
        if ProjectService.unarchive_project(project, root_path):
            ui.notify(f"Restored {project.name} to active portfolio", type="positive")
            self.active_idx = 0
            self.refresh_portfolio()
            self.render_sidebar.refresh()
            self.render_tasks_container.refresh()
            asyncio.create_task(self.update_project_summary())

    def update_task_block(self, task: Task, new_content: str):
        path = task.project_path or self.get_active_project().path
        if not path or not path.exists():
            return
        lines = path.read_text(encoding='utf-8').splitlines()
        if 0 <= task.line_start < len(lines) and task.line_start < task.line_end <= len(lines):
            new_lines = new_content.splitlines()
            lines[task.line_start:task.line_end] = new_lines
            ProjectService.atomic_write(path, "\n".join(lines) + "\n")
            self.refresh_portfolio()
            self.render_sidebar.refresh()
            self.render_tasks_container.refresh()

    async def on_file_changed(self):
        """Callback triggered by ProjectWatcher when notes.md changes externally."""
        AILogger.log("External file modification detected, refreshing UI...", "info")
        self.refresh_portfolio()
        self.render_sidebar.refresh()
        self.render_tasks_container.refresh()
        await self.render_project_summary.refresh()

    async def update_project_summary(self, force: bool = False):
        if getattr(self, 'global_search', False):
            ui.notify("AT A GLANCE requires a specific project. Please turn off 'Aggregated View'.", type="warning", position="top")
            return
            
        project = self.get_active_project()
        if not project.path or not project.path.exists() or project.name == "Empty_Portfolio":
            ui.notify("AT A GLANCE requires an active project. Please select or create one.", type="warning", position="top")
            self.project_summary = "No notes available."
            await self.render_project_summary.refresh()
            return

        content = project.path.read_text(encoding='utf-8', errors='ignore')
        existing = MarkdownParser.extract_summary(content)

        if not force and existing:
            self.project_summary = existing
            await self.render_project_summary.refresh()
            return

        AILogger.log(f"Generating summary for {project.name}...", "ai")
        self.project_summary = "⏳ Generating AI Summary..."
        await self.render_project_summary.refresh()

        project_info = MarkdownParser.extract_project_info(content)
        tasks_portion = re.split(r'^##+\s+ARCHIVE', content, flags=re.MULTILINE | re.IGNORECASE)[0]
        if "## PROJECT SUMMARY" in tasks_portion:
            tasks_portion = re.sub(r'^##+\s+PROJECT SUMMARY.*?(?=\n##+|\Z)', '', tasks_portion, flags=re.DOTALL | re.MULTILINE | re.IGNORECASE)

        prompt = self.config["PROMPT_TEMPLATES"]["Summary"].format(
            tasks_portion=tasks_portion,
            project_info=project_info
        )

        res = await AIEngine.run_prompt(prompt, "Summary", self.config)
        new_summary = res or "Summary unavailable."

        if "⚠️" in new_summary:
            AILogger.log(f"Summary generation warning: {new_summary[:50]}...", "warning")
        else:
            AILogger.log(f"Summary updated for {project.name}", "success")
            updated_content = MarkdownParser.update_summary(content, new_summary)
            ProjectService.atomic_write(project.path, updated_content)

        self.project_summary = new_summary
        await self.render_project_summary.refresh()

    async def run_ai_tool(self, name: str, template: str, input_req: bool = False, force: bool = False):
        project = self.get_active_project()
        
        # Validation: If tool needs specific project notes but we are in Aggregated View
        if "{notes}" in template and "{all_notes}" not in template:
            if getattr(self, 'global_search', False):
                ui.notify(f"The '{name}' tool requires a specific project. Please turn off 'Aggregated View' and select a project.", type="warning", position="top")
                return
            if not project.path or not project.path.exists() or project.name == "Empty_Portfolio":
                ui.notify(f"The '{name}' tool requires an active project. Please select or create one.", type="warning", position="top")
                return
                
        # Validation: General fallback
        if not project.path or not project.path.exists():
            # If it's a portfolio tool (all_notes), we don't necessarily need the active project to exist if there are other projects.
            if "{all_notes}" not in template:
                ui.notify("No active project notes found.", type="warning")
                return

        c_hash = ProjectService.get_content_hash(project.path)
        cache_key = (project.name, name, c_hash)

        if not force and cache_key in self.ai_cache:
            AILogger.log(f"Using cached result for {name}", "info")
            res = self.ai_cache[cache_key]
        else:
            topic = ""
            if input_req:
                topic = await self.prompt_text(name, "Enter focus area or specific technical goal:")
                if not topic:
                    return

            self.processing_status = f"Running {name}..."
            await self.render_header_status.refresh()

            # Aggregate all notes if template requires it
            all_notes_text = ""
            if "{all_notes}" in template:
                for pr in self.projects:
                    if pr.path and pr.path.exists():
                        pr_content = pr.path.read_text(encoding='utf-8', errors='ignore')
                        filtered_pr = AIEngine.filter_private_content(pr_content)
                        if filtered_pr.strip():
                            all_notes_text += f"\n--- PROJECT: {pr.name} ---\n{filtered_pr}\n"

            proj_content = project.path.read_text(encoding='utf-8', errors='ignore') if project.path and project.path.exists() else ""
            filtered_proj_content = AIEngine.filter_private_content(proj_content)

            p_text = template.format(
                project=project.name,
                topic=topic,
                notes=filtered_proj_content,
                all_notes=all_notes_text
            )

            AILogger.log(f"DEBUG run_ai_tool: name={name}", "ai")
            res = await AIEngine.run_prompt(p_text, name, self.config)

            if "⚠️" not in res:
                self.ai_cache[cache_key] = res
                AILogger.log(f"{name} completed successfully", "success")
            else:
                AILogger.log(f"{name} encountered an error: {res[:40]}", "error")

            self.processing_status = ""
            await self.render_header_status.refresh()

        if name == "Refactor Notes":
            self.original_refactor_content = project.path.read_text(encoding='utf-8', errors='ignore')
            self.refactor_content = res
            self.open_refactor_dialog()
        elif name == "Daily Roadmap":
            self.daily_content = res
            self.open_daily_dialog()
        else:
            self.insights_content = f"### {name}\n\n{res}"
            self.open_chat_dialog()

    async def open_standup_dialog(self):
        project = self.get_active_project()
        if not project.path or not project.path.exists():
            ui.notify("No active project notes found.", type="warning")
            return

        self.processing_status = "Generating Standup..."
        await self.render_header_status.refresh()
        content = project.path.read_text(encoding='utf-8', errors='ignore')
        self.standup_content = await AIEngine.generate_standup(project.name, content, self.config)
        self.processing_status = ""
        await self.render_header_status.refresh()

        with ui.dialog() as dialog, ui.card().classes('w-[850px] max-w-[95vw] bg-gray-900 border border-gray-700 p-6 flex flex-col'):
            with ui.row().classes('w-full justify-between items-center mb-3 pb-2 border-b border-gray-800'):
                ui.label(f'Daily Standup • {project.name}').classes('text-xl font-bold text-white')
                ui.button(icon='content_copy', on_click=lambda: ui.run_javascript(f'navigator.clipboard.writeText({repr(self.standup_content)})') or ui.notify('Copied to clipboard!', type='positive')).props('flat dense color=blue').tooltip('Copy to Clipboard')
            with ui.scroll_area().classes('w-full h-[60vh] bg-black/40 p-4 rounded border border-gray-800'):
                ui.markdown(self.standup_content).classes('text-standard text-gray-100')
            ui.button('Close', on_click=dialog.close).props('flat color=blue mt-4 self-end')
        dialog.open()

    def open_dependency_graph_dialog(self):
        tasks = self.parse_active_tasks()
        mermaid_code = MarkdownParser.generate_dependency_mermaid(tasks)

        with ui.dialog() as dialog, ui.card().classes('w-[96vw] max-w-none h-[92vh] bg-gray-900 border border-gray-700 flex flex-col p-6'):
            with ui.row().classes('w-full justify-between items-center mb-3 pb-2 border-b border-gray-800'):
                with ui.row().classes('items-center gap-2'):
                    ui.label('Visual Task Blocker & Dependency Graph (DAG)').classes('text-xl font-bold text-white')
                    ui.badge('Mermaid', color='purple-9').classes('text-[10px]')
                ui.button(icon='close', on_click=dialog.close).props('flat dense color=gray')

            with ui.scroll_area().classes('w-full flex-grow bg-[#0d1117] p-6 rounded-lg border border-gray-800 items-center justify-center'):
                ui.mermaid(mermaid_code).classes('w-full')

            with ui.row().classes('w-full justify-between items-center mt-3 pt-2 border-t border-gray-800'):
                ui.label('Nodes: Red = Blocked, Gold = Dependency, Green = Completed').classes('text-xs text-gray-400')
                ui.button('Close', on_click=dialog.close).props('flat color=blue')
        dialog.open()

    async def open_task_breakdown_dialog(self, task: Task):
        project = self.get_active_project()
        if not project.path:
            return

        with ui.dialog() as dialog, ui.card().classes('w-[700px] max-w-[95vw] bg-gray-900 border border-gray-700 p-6 flex flex-col'):
            ui.label('✨ AI Task Decomposition').classes('text-xl font-bold text-white mb-2')
            ui.label(f'Parent Task: {task.clean_text}').classes('text-sm text-blue-300 font-semibold mb-4')
            
            spinner_box = ui.column().classes('w-full py-8 items-center justify-center')
            with spinner_box:
                ui.spinner(size='lg')
                ui.label('Analyzing task and generating subtasks...').classes('text-xs text-gray-400 mt-2')

            result_box = ui.column().classes('w-full hidden gap-2')
            dialog.open()

            subtasks = await AIEngine.decompose_task(task.clean_text, task.desc, project.name, self.config)
            spinner_box.classes('hidden', remove=True)
            result_box.classes('hidden', add=False)

            with result_box:
                ui.label('Generated Subtasks:').classes('text-xs font-bold text-gray-400')
                subtask_inputs = []
                for st in subtasks:
                    with ui.row().classes('w-full items-center gap-2'):
                        ui.icon('subdirectory_arrow_right', size='16px').classes('text-gray-500')
                        in_elem = ui.input(value=st).classes('flex-grow').props('outlined dark dense')
                        subtask_inputs.append(in_elem)

                with ui.row().classes('w-full justify-end gap-3 mt-4 pt-3 border-t border-gray-800'):
                    ui.button('Cancel', on_click=dialog.close).props('flat color=gray')
                    ui.button('Insert Subtasks into Backlog', on_click=lambda: self.insert_decomposed_subtasks(task, [i.value for i in subtask_inputs], dialog)).props('color=green px-6')

    def insert_decomposed_subtasks(self, parent_task: Task, subtasks: List[str], dialog):
        project = self.get_active_project()
        if not project.path or not project.path.exists():
            return
        content = project.path.read_text(encoding='utf-8')
        updated = MarkdownParser.insert_subtasks(content, parent_task.line_end, subtasks)
        ProjectService.atomic_write(project.path, updated)
        AILogger.log(f"Inserted {len(subtasks)} subtasks under '{parent_task.clean_text[:20]}...'", "success")
        dialog.close()
        self.refresh_portfolio()
        self.render_sidebar.refresh()
        self.render_tasks_container.refresh()

    async def apply_refactor(self):
        project = self.get_active_project()
        if not project.path or not self.refactor_content or "⚠️" in self.refactor_content:
            ui.notify("Invalid refactor content.", type="negative")
            return

        ProjectService.create_backup(project.path)
        ProjectService.atomic_write(project.path, self.refactor_content)
        ui.notify("Refactored notes applied & saved!", type="positive")

        self.ai_cache.clear()
        await self.update_project_summary(force=True)
        self.refresh_portfolio()
        await self.render_sidebar.refresh()
        await self.render_tasks_container.refresh()

        if hasattr(self, 'refactor_dialog'):
            self.refactor_dialog.close()

    async def submit_prompt(self):
        prompt_text = self.cmd_input.value.strip()
        if not prompt_text:
            return

        self.cmd_input.value = ""
        AILogger.log(f"User Prompt: {prompt_text[:30]}...", "info")

        self.processing_status = "Thinking..."
        await self.render_header_status.refresh()

        if getattr(self, 'global_search', False):
            notes_content = ""
            for pr in self.projects:
                if pr.path and pr.path.exists():
                    pr_content = pr.path.read_text(encoding='utf-8', errors='ignore')
                    filtered = AIEngine.filter_private_content(pr_content)
                    if filtered.strip():
                        notes_content += f"\n--- PROJECT: {pr.name} ---\n{filtered}\n"
            project_name = "Aggregated Portfolio View"
        else:
            project = self.get_active_project()
            notes_content = project.path.read_text(encoding='utf-8', errors='ignore') if project.path and project.path.exists() else ""
            notes_content = AIEngine.filter_private_content(notes_content)
            project_name = project.name

        history_context = self.insights_content[-2000:] if self.insights_content else ""

        full_prompt = self.config["PROMPT_TEMPLATES"]["Chat"].format(
            project_name=project_name,
            notes_content=notes_content,
            history_context=history_context,
            prompt_text=prompt_text
        )

        res = await AIEngine.run_prompt(full_prompt, "Chat", self.config)
        
        mode = self.config.get("MODEL_PREFS", {}).get("Chat", "local").upper()
        new_entry = f"**You:** {prompt_text}\n\n**AI ({mode}):**\n{res}\n\n---\n\n"

        if not self.insights_content or self.insights_content == "No chat history.":
            self.insights_content = new_entry
        else:
            self.insights_content += new_entry

        self.processing_status = ""
        await self.render_header_status.refresh()
        self.open_chat_dialog()

    # --- RENDERERS ---

    @ui.refreshable
    def render_header_status(self):
        if self.processing_status:
            with ui.row().classes('items-center gap-2 text-yellow-400'):
                ui.spinner(size='sm')
                ui.label(self.processing_status).classes('text-xs font-bold')
        else:
            ui.label("").classes('hidden')

    @ui.refreshable
    def render_logs(self):
        with ui.column().classes('w-full bg-black/40 p-2 rounded border border-[#21262d] gap-0 h-40'):
            ui.label('SYSTEM LOGS').classes('text-[10px] text-blue-400 font-bold mb-1 tracking-wider')
            with ui.scroll_area().classes('w-full flex-grow'):
                for log_entry in AILogger.logs[-20:]:
                    ui.label(log_entry).classes('text-[10px] text-gray-400 font-mono break-all leading-tight mb-1')

    @ui.refreshable
    def render_project_summary(self):
        with ui.column().classes('w-full bg-[#11161f] border-t border-[#21262d] mt-auto shrink-0 p-3'):
            with ui.row().classes('w-full justify-between items-center mb-1'):
                ui.label('AT A GLANCE').classes('text-header-section text-blue-400')
                ui.button(icon='refresh', on_click=lambda: self.update_project_summary(force=True)).props('flat dense size=xs color=gray').tooltip('Regenerate AI Summary')
            with ui.scroll_area().classes('w-full h-36'):
                ui.markdown(str(self.project_summary)).classes('text-[12px] text-blue-100 leading-relaxed font-normal')

    @ui.refreshable
    def render_sidebar(self):
        with ui.column().classes('gap-1 p-2 w-full'):
            with ui.row().classes('w-full px-2 py-1 items-center justify-between border-b border-gray-800 mb-2'):
                ui.label('PROJECTS').classes('text-[10px] text-gray-400 font-bold tracking-wider')
                ui.button('+ New', icon='add', on_click=self.open_new_project_dialog).props('dense flat size=xs color=blue').tooltip('Create New Project')

            all_p = self.get_all_projects()
            wip_limit_val = int(self.config.get("WIP_LIMIT", 5))

            for i, pr in enumerate(all_p):
                act = (i == self.active_idx) and not self.global_search
                cls = 'sidebar-active shadow-md' if act else 'hover:bg-[#161b22] text-gray-400'
                wip_alert = (pr.todos > wip_limit_val) and not pr.is_archived

                with ui.row().classes(f'w-full items-center p-2 rounded-lg cursor-pointer {cls} no-wrap overflow-hidden justify-between').on('click', lambda idx=i: self.switch_project_async(idx)):
                    with ui.column().classes('gap-0 flex-grow overflow-hidden'):
                        name_cls = f"text-xs truncate font-semibold {'text-white' if act else ('text-red-400 font-bold' if wip_alert else 'text-gray-200')}"
                        ui.label(pr.name).classes(name_cls)
                        ui.label(f"Todos: {pr.todos} | Blockers: {pr.blockers} | {int(pr.progress)}%").classes('text-[9px] opacity-75 font-mono')
                    
                    if not pr.is_archived and pr.name != "Empty_Portfolio":
                        ui.button(icon='archive', on_click=lambda _, idx=i: self.archive_project(idx)).props('flat dense size=xs color=orange @click.stop').tooltip('Archive project')
                    elif pr.is_archived:
                        ui.button(icon='unarchive', on_click=lambda _, idx=i: self.unarchive_project(idx)).props('flat dense size=xs color=green @click.stop').tooltip('Restore project')

            # Archived Projects Toggle
            with ui.row().classes('w-full px-2 pt-3 items-center justify-between border-t border-gray-800/60 mt-2'):
                ui.label('Show Archived').classes('text-[10px] text-gray-500 font-medium')
                ui.switch(value=self.show_archived_p).bind_value(self, 'show_archived_p').on('update:model-value', self.refresh_portfolio).props('dense size=xs')

            # Global Search Toggle
            with ui.row().classes('w-full px-2 pt-1 items-center justify-between'):
                ui.label('Aggregated View').classes('text-[10px] text-gray-500 font-medium')
                ui.switch(value=self.global_search).bind_value(self, 'global_search').on('update:model-value', self.toggle_global_search).props('dense size=xs')

    @ui.refreshable
    def render_tasks_container(self):
        tasks = self.parse_active_tasks()
        with ui.column().classes('col column no-wrap w-full p-3 bg-[#090d13]'):
            
            # HEADER ROW 1: VIEWS, FILTERS, SEARCH & TOGGLES
            with ui.row().classes('w-full mb-2 justify-between items-center shrink-0 flex-wrap'):
                with ui.row().classes('items-center gap-4'):
                    with ui.row().classes('items-center gap-2'):
                        with ui.button_group().props('dense rounded'):
                            ui.button('List', icon='format_list_bulleted', on_click=lambda: self.set_view_mode('list')).props(f"{'color=blue' if self.view_mode == 'list' else 'flat color=gray'} dense size=sm")
                            ui.button('Kanban', icon='view_kanban', on_click=lambda: self.set_view_mode('kanban')).props(f"{'color=blue' if self.view_mode == 'kanban' else 'flat color=gray'} dense size=sm")
                            ui.button('Timeline', icon='timeline', on_click=lambda: self.set_view_mode('timeline')).props(f"{'color=blue' if self.view_mode == 'timeline' else 'flat color=gray'} dense size=sm")
                            ui.button('Analytics', icon='insights', on_click=lambda: self.set_view_mode('analytics')).props(f"{'color=blue' if self.view_mode == 'analytics' else 'flat color=gray'} dense size=sm")
                            ui.button('Raw', icon='code', on_click=lambda: self.set_view_mode('raw')).props(f"{'color=blue' if self.view_mode == 'raw' else 'flat color=gray'} dense size=sm")
                        ui.badge(f"{len(tasks)} items", color='blue-9').classes('text-[10px]')

                    # Filter Pills
                    with ui.row().classes('items-center gap-1'):
                        for f_key, f_label, f_color in [
                            ('all', 'All', 'gray'),
                            ('p1', '🔴 High', 'red'),
                            ('in_progress', '⚡ In Progress', 'blue'),
                            ('blocked', '🛑 Blocked', 'orange'),
                            ('overdue', '📅 Overdue', 'purple')
                        ]:
                            is_sel = (self.filter_type == f_key)
                            ui.button(f_label, on_click=lambda k=f_key: self.set_filter_type(k)).props(f"dense size=xs {'color=' + f_color if is_sel else 'flat color=gray'}")

                # Toggles & Search Input
                with ui.row().classes('items-center gap-3'):
                    with ui.row().classes('items-center gap-2'):
                        ui.checkbox('Show Archived', value=self.show_archived_t).bind_value(self, 'show_archived_t').on('update:model-value', self.render_tasks_container.refresh).classes('text-[10px] text-gray-400')
                        ui.checkbox('Semantic Search', value=self.semantic_mode).bind_value(self, 'semantic_mode').on('update:model-value', self.render_tasks_container.refresh).classes('text-[10px] text-purple-400')
                    self.search_in = ui.input(placeholder='Search tasks (Cmd+K)...', value=self.search_query).on('update:model-value', lambda e: self.update_search(e.args)).classes('w-64 text-sm').props('outlined dark dense rounded')

            # HEADER ROW 2: ADD TASK ONLY
            with ui.row().classes('w-full mb-2 gap-2 items-center shrink-0'):
                self.new_task_input = ui.input(placeholder='Add new task (e.g. Deploy API #p1 @2026-08-20)...').on('keydown.enter', self.add_new_task).classes('flex-grow text-sm').props('outlined dark dense rounded')
                ui.button(icon='add', on_click=self.add_new_task).props('round dense color=blue').tooltip('Add task')

            # BODY: RENDER LIST OR KANBAN
            with ui.element('div').classes('task-body-area col column no-wrap w-full'):
                if self.view_mode == 'list':
                    self.render_list_view(tasks)
                elif self.view_mode == 'kanban':
                    self.render_kanban_view(tasks)
                elif self.view_mode == 'timeline':
                    self.render_timeline_view(tasks)
                elif self.view_mode == 'analytics':
                    self.render_analytics_view(tasks)
                elif self.view_mode == 'raw':
                    self.render_raw_view()

    def set_view_mode(self, mode: str):
        self.view_mode = mode
        self.render_tasks_container.refresh()

    def set_filter_type(self, f_type: str):
        self.filter_type = f_type
        self.render_tasks_container.refresh()

    def update_search(self, val: str):
        self.search_query = str(val or "")
        self.render_tasks_container.refresh()



    def render_list_view(self, tasks: List[Task]):
        with ui.element('div').classes('list-area col column w-full pb-10'):
            if not tasks:
                with ui.column().classes('w-full h-64 items-center justify-center text-gray-500'):
                    ui.icon('task_alt', size='48px').classes('opacity-30 mb-2')
                    ui.label('No matching tasks found.').classes('text-sm')
            else:
                for t in tasks:
                    with ui.row().classes('w-full items-center justify-between p-2.5 mb-2 bg-[#11161f] rounded-xl border border-[#21262d] task-card cursor-pointer no-wrap overflow-hidden').on('click', lambda _, task=t: self.open_task_details(task)):
                        with ui.row().classes('items-center gap-3 flex-grow no-wrap overflow-hidden'):
                            if t.is_done:
                                ui.icon('check_box').classes('text-blue-500 text-[16px]')
                            else:
                                ui.icon('check_box_outline_blank').classes('text-gray-600 text-[16px]')

                            if t.prio <= 3:
                                colors = {1: 'bg-red-600 text-white', 2: 'bg-yellow-500 text-black', 3: 'bg-green-600 text-white'}
                                symbols = {1: 'HIGH', 2: 'MED', 3: 'LOW'}
                                ui.label(symbols[t.prio]).classes(f'text-[9px] px-1.5 py-0.5 rounded font-black {colors[t.prio]}')

                            if t.kanban_status == "in_progress" and not t.is_done:
                                ui.badge('IN PROGRESS', color='blue-8').classes('text-[9px]')

                            if self.global_search and t.project_path:
                                pname = t.project_path.parent.name
                                ui.badge(pname, color=get_project_color(pname)).classes('text-[11px] font-bold px-1.5 py-0.5')

                            with ui.column().classes('gap-0 flex-grow overflow-hidden'):
                                ui.markdown(t.clean_text).classes(f"{'text-gray-500 line-through' if t.is_done else 'text-gray-100'} text-[15px] font-bold truncate")
                                if t.desc:
                                    ui.label(t.desc).classes('text-[11px] text-gray-400 truncate')
                                if t.body_lines:
                                    ui.markdown("\n".join(t.body_lines)).classes('text-[11px] text-gray-400 mt-1 pl-2 border-l-2 border-gray-700')

                        with ui.column().classes('gap-1'):
                            ui.button(icon='expand_less', on_click=lambda _, task=t: self.move_task(task, -1)).props('flat dense size=xs color=gray @click.stop')
                            ui.button(icon='expand_more', on_click=lambda _, task=t: self.move_task(task, 1)).props('flat dense size=xs color=gray @click.stop')
                            if t.due:
                                ui.label(f'📅 {t.due}').classes(f"text-[10px] {'text-red-400 font-bold' if t.overdue else 'text-gray-400'}")
                            if t.blocked:
                                ui.icon('block', size='16px').classes('text-red-500').tooltip(f"Blocked by: {t.blocked}")
                            if t.dep:
                                ui.icon('link', size='16px').classes('text-orange-500').tooltip(f"Depends on: {t.dep}")
                            if t.is_archived:
                                ui.icon('history', size='16px').classes('text-gray-600').tooltip('Archived Task')

    def render_kanban_view(self, tasks: List[Task]):
        columns = [
            ("todo", "📋 TO DO", [t for t in tasks if t.kanban_status == "todo"]),
            ("in_progress", "⚡ IN PROGRESS", [t for t in tasks if t.kanban_status == "in_progress"]),
            ("blocked", "🛑 BLOCKED", [t for t in tasks if t.kanban_status == "blocked"]),
            ("done", "✅ DONE", [t for t in tasks if t.kanban_status == "done"])
        ]

        with ui.row().classes('kanban-grid no-wrap items-start w-full col gap-3 pb-10'):
            for col_id, col_title, col_tasks in columns:
                with ui.column().classes('kanban-column col column no-wrap h-full'):
                    with ui.row().classes('kanban-header justify-between items-center w-full shrink-0'):
                        ui.label(col_title).classes('text-gray-300')
                        ui.badge(str(len(col_tasks)), color='blue-9' if col_id != 'blocked' else 'red-9').classes('text-[10px]')
                    
                    with ui.column().classes('col w-full p-2'):
                        for t in col_tasks:
                            with ui.card().classes('w-full mb-2 p-2.5 bg-[#090d13] border border-[#21262d] rounded-lg task-card cursor-pointer').on('click', lambda _, task=t: self.open_task_details(task)):
                                with ui.row().classes('w-full justify-between items-start mb-1'):
                                    if t.prio <= 3:
                                        colors = {1: 'bg-red-600 text-white', 2: 'bg-yellow-500 text-black', 3: 'bg-green-600 text-white'}
                                        ui.label(f'#p{t.prio}').classes(f'text-[8px] px-1 py-0.5 rounded font-black {colors[t.prio]}')
                                    else:
                                        ui.label('')
                                    if t.due:
                                        ui.label(f'📅 {t.due}').classes(f"text-[9px] {'text-red-400 font-bold' if t.overdue else 'text-gray-400'}")
                                    if self.global_search and t.project_path:
                                        pname = t.project_path.parent.name
                                        ui.badge(pname, color=get_project_color(pname)).classes('text-[10px] font-bold px-1.5 py-0.5')

                                ui.label(t.clean_text).classes(f"text-sm font-bold {'text-gray-500 line-through' if t.is_done else 'text-white'} mb-1 leading-tight")
                                if t.desc:
                                    ui.label(t.desc).classes('text-[10px] text-gray-400 mb-2 line-clamp-2')
                                if t.body_lines:
                                    ui.markdown("\n".join(t.body_lines)).classes('text-[10px] text-gray-400 mb-2 pl-1 border-l-2 border-gray-700 overflow-hidden line-clamp-3')
                                if t.blocked:
                                    ui.label(f"🛑 {t.blocked}").classes('text-[10px] text-red-400 font-semibold mb-1')

                                with ui.row().classes('w-full justify-end items-center pt-2 border-t border-gray-800'):
                                    with ui.row().classes('gap-1'):
                                        if col_id != "todo":
                                            ui.button(icon='chevron_left', on_click=lambda _, task=t: self.move_kanban_status(task, -1)).props('flat dense size=xs color=gray @click.stop').tooltip('Move Left')
                                        
                                        ui.button(icon='auto_fix_high', on_click=lambda _, task=t: self.open_task_breakdown_dialog(task)).props('flat dense size=xs color=purple @click.stop').tooltip('✨ Break Down')
                                        
                                        if col_id != "done":
                                            ui.button(icon='chevron_right', on_click=lambda _, task=t: self.move_kanban_status(task, 1)).props('flat dense size=xs color=gray @click.stop').tooltip('Move Right')

    def render_timeline_view(self, tasks: List[Task]):
        if not tasks:
            ui.label('No tasks to show.').classes('text-gray-500 italic p-4')
            return
            
        gantt_lines = ["%%{init: {'theme': 'dark', 'themeVariables': {'textColor': '#e5e7eb', 'primaryTextColor': '#e5e7eb', 'titleColor': '#ffffff'}}}%%", "gantt", "    title Project Timeline", "    dateFormat YYYY-MM-DD", "    axisFormat %m/%d"]
        
        # Group tasks by project
        from collections import defaultdict
        tasks_by_proj = defaultdict(list)
        has_due = False
        
        for t in tasks:
            if not t.due:
                continue
            has_due = True
            proj_name = t.project_path.stem if t.project_path else "Tasks"
            tasks_by_proj[proj_name].append(t)
            
        if not has_due:
            ui.label('No tasks with a due date (@YYYY-MM-DD) found.').classes('text-gray-500 italic p-4')
            return
            
        for proj_name, p_tasks in tasks_by_proj.items():
            gantt_lines.append(f"    section {proj_name}")
            for t in p_tasks:
                status_str = "done, " if t.is_done else "active, " if t.kanban_status == "in_progress" else ""
                clean_name = t.clean_text.replace('"', '').replace(':', '').replace(',', '').replace('#', '').replace('^', '')
                if t.created and t.due:
                    gantt_lines.append(f"    {clean_name} : {status_str}id_{t.id}, {t.created}, {t.due}")
                else:
                    gantt_lines.append(f"    {clean_name} : {status_str}id_{t.id}, {t.due}, 1d")
            
        mermaid_code = "\n".join(gantt_lines)
        with ui.card().classes('w-full bg-[#090d13] border border-[#21262d]'):
            ui.mermaid(mermaid_code).classes('w-full')

    def render_analytics_view(self, tasks: List[Task]):
        with ui.element('div').classes('list-area col w-full p-4 overflow-y-auto'):
            if not tasks:
                with ui.column().classes('w-full h-64 items-center justify-center text-gray-500'):
                    ui.icon('insights', size='48px').classes('opacity-30 mb-2')
                    ui.label('No tasks available for analytics.').classes('text-sm')
                return
                
            # Aggregate data
            status_counts = {"todo": 0, "in_progress": 0, "blocked": 0, "done": 0}
            prio_counts = {1: 0, 2: 0, 3: 0, 4: 0}
            for t in tasks:
                status_counts[t.kanban_status] += 1
                prio_counts[t.prio] += 1
                
            with ui.row().classes('w-full gap-4'):
                # Project Health Donut Chart
                with ui.card().classes('bg-[#11161f] border border-[#21262d] p-4 flex-grow w-[45%]'):
                    ui.label('Project Health').classes('text-xs font-bold text-gray-400 mb-2 tracking-wider uppercase')
                    ui.echarts({
                        'tooltip': {'trigger': 'item'},
                        'legend': {'top': '5%', 'left': 'center', 'textStyle': {'color': '#8b949e'}},
                        'series': [
                            {
                                'name': 'Tasks',
                                'type': 'pie',
                                'radius': ['40%', '70%'],
                                'avoidLabelOverlap': False,
                                'itemStyle': {
                                    'borderRadius': 10,
                                    'borderColor': '#11161f',
                                    'borderWidth': 2
                                },
                                'label': {'show': False, 'position': 'center'},
                                'labelLine': {'show': False},
                                'data': [
                                    {'value': status_counts['done'], 'name': 'Done', 'itemStyle': {'color': '#2ea043'}},
                                    {'value': status_counts['in_progress'], 'name': 'In Progress', 'itemStyle': {'color': '#3b82f6'}},
                                    {'value': status_counts['blocked'], 'name': 'Blocked', 'itemStyle': {'color': '#f85149'}},
                                    {'value': status_counts['todo'], 'name': 'To Do', 'itemStyle': {'color': '#6e7681'}}
                                ]
                            }
                        ]
                    }).classes('h-64')

                # Priority Distribution Bar Chart
                with ui.card().classes('bg-[#11161f] border border-[#21262d] p-4 flex-grow w-[45%]'):
                    ui.label('Priority Backlog').classes('text-xs font-bold text-gray-400 mb-2 tracking-wider uppercase')
                    ui.echarts({
                        'tooltip': {'trigger': 'axis'},
                        'xAxis': {
                            'type': 'category', 
                            'data': ['P1 (High)', 'P2 (Med)', 'P3 (Low)', 'Unprioritized'],
                            'axisLabel': {'color': '#8b949e'}
                        },
                        'yAxis': {'type': 'value', 'splitLine': {'lineStyle': {'color': '#21262d'}}, 'axisLabel': {'color': '#8b949e'}},
                        'series': [{
                            'data': [
                                {'value': prio_counts[1], 'itemStyle': {'color': '#dc2626'}},
                                {'value': prio_counts[2], 'itemStyle': {'color': '#eab308'}},
                                {'value': prio_counts[3], 'itemStyle': {'color': '#16a34a'}},
                                {'value': prio_counts[4], 'itemStyle': {'color': '#4b5563'}}
                            ],
                            'type': 'bar',
                            'barWidth': '40%'
                        }]
                    }).classes('h-64')

    def render_raw_view(self):
        p = self.get_active_project()
        if not p or not p.path or not p.path.exists():
            ui.label('No notes.md available.').classes('text-gray-500 p-4')
            return
            
        content = p.path.read_text(encoding='utf-8', errors='ignore')
        
        async def _save():
            ProjectService.atomic_write(p.path, raw_input.value)
            ui.notify('Raw notes saved!', type='positive')
            self.refresh_portfolio()
            self.render_tasks_container.refresh()
            
        with ui.column().classes('w-full h-full gap-2 p-0'):
            with ui.row().classes('w-full justify-between items-center bg-[#161b22] border-b border-[#30363d] p-3'):
                ui.label(f'Editing: {p.name}/notes.md').classes('text-sm font-mono font-bold text-gray-300')
                ui.button('Save Notes', on_click=_save, icon='save').props('color=blue size=sm')

            with ui.splitter(value=50).classes('w-full h-[75vh] flex-grow') as splitter:
                with splitter.before:
                    raw_input = ui.textarea(value=content).classes('w-full h-full font-mono text-sm bg-[#0d1117] text-gray-300').props('dark autogrow borderless')
                with splitter.after:
                    with ui.card().classes('w-full h-full overflow-y-auto bg-[#0d1117] border-none text-gray-300 shadow-none'):
                        preview = ui.markdown(content).classes('w-full markdown-body')

            raw_input.on_value_change(lambda e: preview.set_content(e.value))

    # --- DIALOGS ---

    def open_new_project_dialog(self):
        with ui.dialog() as dialog, ui.card().classes('w-[550px] max-w-[95vw] bg-gray-900 border border-gray-700 p-6 flex flex-col'):
            ui.label('Create New Project').classes('text-xl font-bold text-white mb-3')
            name_in = ui.input('Project Name', placeholder='e.g. Billing_Service').classes('w-full').props('outlined dark dense auto-focus')
            mission_in = ui.textarea('Mission & Goals', placeholder='Key architectural mission...').classes('w-full').props('outlined dark dense')
            tech_in = ui.input('Tech Stack', placeholder='e.g. Python, FastAPI, Postgres, Redis').classes('w-full').props('outlined dark dense')
            lead_in = ui.input('Lead Engineer', placeholder='e.g. Jane Doe (jane@company.com)').classes('w-full').props('outlined dark dense')

            with ui.row().classes('w-full justify-end gap-3 mt-4 pt-3 border-t border-gray-800'):
                ui.button('Cancel', on_click=dialog.close).props('flat color=gray')
                async def _save():
                    name_val = name_in.value.strip()
                    if not name_val:
                        ui.notify('Please enter a project name', type='warning')
                        return
                    root_path = Path(self.config["PROJECTS_ROOT"])
                    new_proj = ProjectService.create_new_project(
                        root_path,
                        name_val,
                        mission=mission_in.value.strip(),
                        tech_stack=tech_in.value.strip(),
                        lead=lead_in.value.strip()
                    )
                    dialog.close()
                    self.refresh_portfolio()
                    # Find index of newly created project
                    all_p = self.get_all_projects()
                    for idx, p in enumerate(all_p):
                        if p.name == new_proj.name:
                            self.active_idx = idx
                            break
                    await self.render_sidebar.refresh()
                    await self.render_tasks_container.refresh()
                    await self.update_project_summary(force=True)
                    ui.notify(f"Created project '{new_proj.name}'", type="positive")

                ui.button('Create Project', on_click=_save).props('color=blue px-6')
        dialog.open()

    async def open_task_details(self, task: Task):
        with ui.dialog() as dialog, ui.card().classes('w-[900px] max-w-[95vw] h-[750px] bg-gray-900 border border-gray-700 p-6 flex flex-col'):
            with ui.row().classes('w-full justify-between items-center mb-3'):
                ui.label('Task Details').classes('text-xl font-bold text-white')
                with ui.row().classes('gap-2'):
                    ui.button('✨ AI Break Down', icon='auto_fix_high', on_click=lambda: self.open_task_breakdown_dialog(task)).props('flat dense color=purple')
                    ui.button('✨ AI Refactor', icon='edit_note', on_click=lambda: self.run_ai_tool('Refactor Task', self.config["PROMPT_TEMPLATES"]["Refactor Task"].format(task_text=task.raw_text))).props('flat dense color=blue')

            with ui.column().classes('w-full flex-grow gap-4'):
                desc_input = ui.input('Title', value=task.clean_text).classes('w-full').props('outlined dark')
                desc_long = ui.textarea('Inline Description / Context', value=task.desc).classes('w-full').props('outlined dark')
                body_input = ui.textarea('Multi-line Body (Markdown)', value="\n".join(task.body_lines or [])).classes('w-full flex-grow').props('outlined dark')
                
                with ui.row().classes('w-full gap-4'):
                    block = ui.input('Blocker Tag (#blocked: ...)', value=task.blocked or '').classes('w-1/2').props('outlined dark dense')
                    dep = ui.input('Dependency Tag (#dep: ...)', value=task.dep or '').classes('w-1/2').props('outlined dark dense')
                
                with ui.row().classes('w-full gap-4 items-center'):
                    status_select = ui.select(
                        {'todo': 'To Do', 'in_progress': 'In Progress (#in_progress)', 'blocked': 'Blocked (#blocked)', 'done': 'Completed [x]'},
                        value=task.kanban_status,
                        label='Status'
                    ).classes('w-56').props('outlined dark dense')
                    
                    prio_sel = ui.select({1: 'High (#p1)', 2: 'Medium (#p2)', 3: 'Low (#p3)', 4: 'None'}, value=task.prio, label='Priority').classes('w-44').props('outlined dark dense')
                    
                    with ui.input('Created Date (^YYYY-MM-DD)', value=task.created or '').classes('w-56').props('outlined dark dense') as date_created_in:
                        with ui.menu() as menu_created:
                            ui.date().bind_value(date_created_in).on('update:model-value', menu_created.close)
                        with date_created_in.add_slot('append'):
                            ui.icon('edit_calendar').on('click', menu_created.open).classes('cursor-pointer')

                    with ui.input('Due Date (@YYYY-MM-DD)', value=task.due or '').classes('w-56').props('outlined dark dense') as date_in:
                        with ui.menu() as menu:
                            ui.date().bind_value(date_in).on('update:model-value', menu.close)
                        with date_in.add_slot('append'):
                            ui.icon('edit_calendar').on('click', menu.open).classes('cursor-pointer')

            with ui.row().classes('w-full justify-between mt-4 pt-3 border-t border-gray-800'):
                with ui.row().classes('gap-2'):
                    ui.button('Delete Task', on_click=lambda: self.delete_task(task, dialog)).props('flat color=red')
                    ui.button('Archive Task', on_click=lambda: self.archive_task(task) or dialog.submit(None)).props('flat color=orange')
                ui.button('Close', on_click=lambda: dialog.submit('close')).props('flat color=gray px-6')

        await dialog
        # Auto-save when dialog closes (either by clicking Close, or clicking outside)
        sel_status = status_select.value
        is_done = (sel_status == 'done')
        updated_task = Task(
            id=task.id,
            line_start=task.line_start,
            line_end=task.line_end,
            clean_text=desc_input.value.strip(),
            raw_text="",
            is_done=is_done,
            prio=prio_sel.value,
            blocked=block.value.strip() or None,
            dep=dep.value.strip() or None,
            desc=desc_long.value.strip(),
            due=date_in.value.strip() or None,
            created=date_created_in.value.strip() or None,
            status_override=status_select.value,
            body_lines=body_input.value.strip().splitlines() if body_input.value.strip() else None
        )
        self.update_task_block(task, updated_task.to_markdown_line())

    def open_chat_dialog(self):
        with ui.dialog() as dialog, ui.card().classes('w-[96vw] max-w-none h-[92vh] bg-gray-900 border border-gray-700 flex flex-col p-6'):
            with ui.row().classes('w-full justify-between items-center mb-3 pb-2 border-b border-gray-800'):
                ui.label('AI TPM Chat & Insights').classes('text-xl font-bold text-white')
                with ui.row().classes('items-center gap-3'):
                    ui.button(icon='refresh', on_click=lambda: self.run_ai_tool("Chat", "{all_notes}" if getattr(self, 'global_search', False) else "{notes}", force=True)).props('flat color=gray').tooltip('Refresh Context')
            with ui.scroll_area().classes('w-full flex-grow p-6 bg-black/30 rounded-lg border border-gray-800'):
                ui.markdown(self.insights_content or "No chat history.").classes('text-standard text-gray-100')
            ui.button('Close', on_click=dialog.close).props('flat color=blue mt-4 self-end')
        dialog.open()

    def open_daily_dialog(self):
        with ui.dialog() as dialog, ui.card().classes('w-[96vw] max-w-none h-[92vh] bg-gray-900 border border-gray-700 flex flex-col p-6'):
            with ui.row().classes('w-full justify-between items-center mb-3 pb-2 border-b border-gray-800'):
                ui.label('Portfolio Daily Roadmap').classes('text-xl font-bold text-white')
                ui.button(icon='refresh', on_click=lambda: self.run_ai_tool('Daily Roadmap', self.config["PROMPT_TEMPLATES"]["Daily Roadmap"].replace("{all_notes}", "{all_notes}"), force=True)).props('flat color=gray')
            with ui.scroll_area().classes('w-full flex-grow p-6 bg-black/30 rounded-lg border border-gray-800'):
                ui.markdown(self.daily_content).classes('text-standard text-gray-100')
            ui.button('Close', on_click=dialog.close).props('flat color=blue mt-4 self-end')
        dialog.open()

    def open_refactor_dialog(self):
        with ui.dialog() as self.refactor_dialog, ui.card().classes('w-[96vw] max-w-none h-[92vh] bg-gray-900 border border-gray-700 flex flex-col p-6'):
            with ui.row().classes('w-full justify-between items-center mb-3 pb-2 border-b border-gray-800'):
                ui.label('Refactor Notes (Diff Preview)').classes('text-xl font-bold text-white')
                ui.button(icon='refresh', on_click=lambda: self.run_ai_tool('Refactor Notes', self.config["PROMPT_TEMPLATES"]["Refactor Notes"].replace("{project}", "{project}").replace("{notes}", "{notes}"), force=True)).props('flat color=gray')
            
            with ui.row().classes('w-full flex-grow gap-4 min-h-0'):
                with ui.column().classes('w-1/2 h-full'):
                    ui.label('Original Notes').classes('text-xs font-bold text-gray-400 mb-1')
                    with ui.scroll_area().classes('w-full h-full bg-black/40 border border-gray-800 p-4 rounded'):
                        ui.markdown(self.original_refactor_content).classes('text-xs text-gray-300 font-mono')
                
                with ui.column().classes('w-1/2 h-full'):
                    ui.label('Refactored Proposal').classes('text-xs font-bold text-green-400 mb-1')
                    with ui.scroll_area().classes('w-full h-full bg-black/40 border border-gray-800 p-4 rounded'):
                        ui.markdown(self.refactor_content).classes('text-xs text-green-100 font-mono')

            with ui.row().classes('w-full justify-end gap-4 mt-4'):
                ui.button('Discard', on_click=self.refactor_dialog.close).props('flat color=red')
                ui.button('Accept & Apply Backup', on_click=self.apply_refactor).props('color=green px-6')
        self.refactor_dialog.open()

    def open_config_dialog(self):
        with ui.dialog() as dialog, ui.card().classes('w-[850px] max-w-[95vw] bg-gray-900 border border-gray-700 p-8 flex flex-col'):
            ui.label('System & AI Configuration').classes('text-xl font-bold text-white mb-2')
            
            with ui.tabs().classes('w-full text-blue-400') as tabs:
                general_tab = ui.tab('General Settings')
                prompt_tab = ui.tab('Prompt Studio')

            with ui.tab_panels(tabs, value=general_tab).classes('w-full bg-transparent p-0'):
                with ui.tab_panel(general_tab):
                    with ui.column().classes('w-full gap-4 max-h-[60vh] overflow-y-auto pr-2 pt-2'):
                        ui.input('Projects Root Directory', value=self.config["PROJECTS_ROOT"]).bind_value(self.config, 'PROJECTS_ROOT').props('outlined dark dense')
                        
                        with ui.row().classes('w-full gap-4'):
                            ui.input('Cloud Model (Copilot)', value=self.config["CLOUD_MODEL"]).bind_value(self.config, 'CLOUD_MODEL').props('outlined dark dense').classes('w-1/2')
                            ui.input('Local Model (Ollama)', value=self.config["LOCAL_MODEL"]).bind_value(self.config, 'LOCAL_MODEL').props('outlined dark dense').classes('w-1/2')

                        with ui.row().classes('w-full gap-4'):
                            ui.input('Ollama Base URL', value=self.config["OLLAMA_BASE_URL"]).bind_value(self.config, 'OLLAMA_BASE_URL').props('outlined dark dense').classes('w-1/2')
                            ui.number('WIP Limit (Red Alert)', value=int(self.config.get("WIP_LIMIT", 5)), min=1, step=1).bind_value(self.config, 'WIP_LIMIT').props('outlined dark dense').classes('w-1/2')

                        ui.label('TOOL ENGINE PREFERENCES').classes('text-header-section text-blue-400 mt-2')
                        with ui.grid(columns=2).classes('w-full gap-3'):
                            for tool in ["Summary", "Daily Roadmap", "Executive", "Triage", "Groom", "Tech Plan", "Refactor Task", "Refactor Notes", "Chat"]:
                                ui.select(['local', 'cloud'], label=tool, value=self.config["MODEL_PREFS"].get(tool, 'local')).bind_value(self.config["MODEL_PREFS"], tool).props('dense dark outlined')

                with ui.tab_panel(prompt_tab):
                    with ui.column().classes('w-full gap-6 max-h-[60vh] overflow-y-auto pr-2 pt-2'):
                        ui.label('Master Prompts Editor').classes('text-header-section text-purple-400 mb-2')
                        for tool in self.config["PROMPT_TEMPLATES"].keys():
                            ui.textarea(tool, value=self.config["PROMPT_TEMPLATES"][tool]).bind_value(self.config["PROMPT_TEMPLATES"], tool).props('outlined dark autogrow').classes('w-full font-mono text-xs')

            with ui.row().classes('w-full justify-end gap-3 mt-6 pt-3 border-t border-gray-800'):
                ui.button('Cancel', on_click=dialog.close).props('flat color=gray')
                ui.button('Save & Apply', on_click=lambda: self.save_and_apply_config(dialog)).props('color=blue px-6')
        dialog.open()

    def save_and_apply_config(self, dialog):
        self.config = save_config(self.config)
        ui.notify("Configuration saved successfully", type="positive")
        dialog.close()
        self.refresh_portfolio()
        self.render_sidebar.refresh()

    async def prompt_text(self, title: str, message: str, default: str = '') -> str:
        with ui.dialog() as dialog, ui.card().classes('w-96 bg-gray-900 border border-gray-700 p-4'):
            ui.label(title).classes('text-lg font-bold text-white')
            ui.label(message).classes('text-xs text-gray-400 mb-2')
            i = ui.input(value=default).classes('w-full').props('outlined dark dense auto-focus')
            ui.button('Confirm', on_click=lambda: dialog.submit(i.value)).props('color=blue w-full mt-3')
        return await dialog or ""

    def setup_ui(self):
        self.dark_mode = ui.dark_mode()
        self.dark_mode.enable()
        ui.add_head_html(f'<style>{CUSTOM_CSS}</style>')

        # Register Cmd+K / Ctrl+K keyboard shortcut to focus search
        def _handle_keyboard(e):
            try:
                if e.key == 'k' and (e.modifiers.meta or e.modifiers.ctrl) and e.action.keydown:
                    self.search_in.run_method('focus')
            except Exception:
                pass
        ui.keyboard(on_key=_handle_keyboard)

        # HEADER
        with ui.header().classes('p-2.5 bg-[#11161f] border-b border-[#21262d] no-wrap items-center'):
            with ui.row().classes('items-center gap-3 shrink-0'):
                ui.button(icon='menu', on_click=lambda: self.drawer.toggle()).props('flat color=white dense')
                ui.label('TPM COMMAND CENTER').classes('text-base font-bold text-white tracking-wider')

            with ui.row().classes('items-center justify-center gap-1.5 grow'):
                for tool, ttip, tmpl_key in [
                    ('EXECUTIVE', 'Generate a high-level ROI and business impact summary', 'Executive'),
                    ('GROOM', 'Reorganize and prioritize the TO DO backlog based on dependencies', 'Groom'),
                    ('TRIAGE', 'Scan all projects for stale tasks, blockers, and risks', 'Triage')
                ]:
                    ui.button(tool, on_click=lambda t=tool, k=tmpl_key: self.run_ai_tool(t.title(), self.config["PROMPT_TEMPLATES"][k], input_req=False)).props('flat color=blue dense').classes('text-xs font-bold px-2').tooltip(ttip)

                ui.button('DAILY', on_click=lambda: self.run_ai_tool('Daily Roadmap', self.config["PROMPT_TEMPLATES"]["Daily Roadmap"])).props('flat color=blue dense').classes('text-xs font-bold px-2').tooltip('Generate a cross-project daily roadmap highlighting urgent items')
                ui.button(icon='settings', on_click=self.open_config_dialog).props('flat color=gray dense').classes('px-2').tooltip('Settings & API Keys')

            with ui.row().classes('items-center justify-end gap-2 shrink-0'):
                with ui.column().classes('items-end gap-0 w-[450px]'):
                    self.render_header_status()
                    self.render_logs()

        # LEFT DRAWER (PORTFOLIO & AT A GLANCE - Compact ~300px)
        self.drawer = ui.left_drawer(value=True).props('width=300').classes('bg-[#090d13] border-r border-[#21262d] p-0 flex flex-col')
        with self.drawer:
            with ui.column().classes('w-full h-full no-wrap'):
                with ui.scroll_area().classes('w-full flex-grow'):
                    self.render_sidebar()
                self.render_project_summary()

        # MAIN TASK BACKLOG / KANBAN VIEW (Full Space Real Estate)
        with ui.element('div').classes('main-content-area col column no-wrap w-full'):
            self.render_tasks_container()

        # FOOTER (AI PROMPT BAR & TOGGLE)
        with ui.footer().classes('bg-[#11161f] border-t border-[#21262d] p-2.5 shrink-0'):
            with ui.row().classes('w-full items-center gap-3'):
                self.cmd_input = ui.input(placeholder='Ask AI anything about the active project notes...').on('keydown.enter', self.submit_prompt).classes('flex-grow text-sm').props('outlined dark dense rounded')
                ui.button(icon='send', on_click=self.submit_prompt).props('elevated color=blue dense').tooltip('Submit prompt')
