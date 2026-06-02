import os
import subprocess
import datetime
import re
import sys
import asyncio
import json
import hashlib
from pathlib import Path
from nicegui import ui, app, run

# --- CONFIGURATION PERSISTENCE ---
CONFIG_FILE = "tpm_config.json"

def load_config():
    default = {
        "PROJECTS_ROOT": "projects",
        "GLOBAL_MODEL_CMD": "gh copilot chat -p",
        "WIP_LIMIT": 8,
        "MODEL_PREFS": {
            "Summary": "local",
            "Chat": "local",
            "Daily Roadmap": "local",
            "Refactor Notes": "local",
            "Executive": "cloud",
            "Tech Plan": "cloud",
            "Health": "local",
            "Risks": "local"
        }
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                loaded = json.load(f)
                if "MODEL_PREFS" in loaded:
                    default["MODEL_PREFS"].update(loaded["MODEL_PREFS"])
                    del loaded["MODEL_PREFS"]
                return {**default, **loaded}
        except Exception:
            return default
    return default

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)

CONFIG = load_config()

# --- UTILS ---
def clean_ansi(text):
    """Removes ANSI escape codes from LLM responses."""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

def get_content_hash(path):
    """Generates a hash of file content to detect changes for caching."""
    if not path or not path.exists(): return ""
    return hashlib.md5(path.read_bytes()).hexdigest()

# --- ENTERPRISE AI ENGINE ---
class AIEngine:
    @staticmethod
    def run_local(prompt):
        try:
            res = subprocess.run(['ollama', 'run', "llama3.2:3b", prompt], 
                                capture_output=True, text=True, encoding='utf-8', timeout=60)
            if res.returncode != 0: return "model is not available"
            return clean_ansi(res.stdout.strip())
        except Exception: return "model is not available"

    @staticmethod
    def run_copilot(prompt):
        try:
            subprocess.run(['gh', '--version'], capture_output=True, check=True)
            cmd_parts = CONFIG["GLOBAL_MODEL_CMD"].split() + [prompt]
            res = subprocess.run(cmd_parts, capture_output=True, text=True, encoding='utf-8', timeout=60)
            if res.returncode != 0: return "model is not available"
            return clean_ansi(res.stdout.strip())
        except Exception:
            return "model is not available"

# --- TPM MISSION CONTROL ---
class WebTPM:
    def __init__(self):
        self.active_idx = 0
        self.projects = []
        self.archived_projects = []
        self.insights_content = ""
        self.daily_content = "No roadmap generated yet."
        self.refactor_content = "No refactor preview available."
        self.processing_status = ""
        self.session_buffer = [] 
        self.project_summary = "Select a project to view its summary."
        self.ai_mode = "local"
        self.ai_cache = {} 
        self.show_archived_p = False
        self.show_archived_t = False
        
        # Config bindings
        self.c_root = CONFIG["PROJECTS_ROOT"]
        self.c_model = CONFIG["GLOBAL_MODEL_CMD"]
        self.c_wip = str(CONFIG["WIP_LIMIT"])
        self.model_prefs = CONFIG["MODEL_PREFS"]

        self.refresh_projects()
        self.setup_ui()
        
        if self.projects and self.projects[0]['name'] != "Empty_Portfolio":
            ui.timer(0.1, self.update_project_summary, once=True)

    def refresh_projects(self):
        root = Path(CONFIG["PROJECTS_ROOT"])
        root.mkdir(exist_ok=True)
        
        def scan_dir(path, is_archived=False):
            projs = []
            if not path.exists(): return projs
            dirs = sorted([d for d in path.iterdir() if d.is_dir() and not d.name.startswith('_')])
            for d in dirs:
                n_path = d / "notes.md"
                tc, bc, uc, dc, tot = 0, 0, 0, 0, 0
                if n_path.exists():
                    try:
                        c = n_path.read_text(encoding='utf-8', errors='ignore')
                        ls = c.splitlines()
                        ts = [l for l in ls if re.match(r'^\s*-\s?\[[\sxX]\]', l)]
                        tot = len(ts)
                        dc = len([l for l in ts if re.search(r'\[[xX]\]', l)])
                        tc = len([l for l in ts if re.match(r'^\s*-\s?\[\s\]', l) and "#blocked" not in l])
                        bc = len([l for l in ls if "#blocked" in l])
                        uc = len(re.findall(r'#urgent|#high|\[!\]', c, re.IGNORECASE))
                    except: pass
                prog = (dc / tot * 100) if tot > 0 else 0
                projs.append({"name": d.name, "todos": tc, "blockers": bc, "urgent": uc, "progress": prog, "path": n_path, "dir": d, "is_archived": is_archived})
            return projs

        self.projects = scan_dir(root)
        if self.show_archived_p:
            self.archived_projects = scan_dir(root / "_Archive_2026", is_archived=True)
        else:
            self.archived_projects = []

        if not self.projects and not self.archived_projects:
            self.projects = [{"name": "Empty_Portfolio", "todos": 0, "blockers": 0, "urgent": 0, "progress": 0, "path": None, "dir": None, "is_archived": False}]

    def parse_tasks(self):
        all_p = self.projects + self.archived_projects
        if self.active_idx >= len(all_p): self.active_idx = 0
        p = all_p[self.active_idx]
        if not p['path'] or not p['path'].exists(): return []
        content = p['path'].read_text(encoding='utf-8', errors='ignore')
        
        # Strip summary and archive from active task parsing
        active_part = content
        archive_part = ""
        if "## ARCHIVE" in active_part:
            active_part, archive_part = active_part.split("## ARCHIVE", 1)
        if "## PROJECT SUMMARY" in active_part:
            active_part = active_part.split("## PROJECT SUMMARY")[0]

        def extract_tasks(text, archived=False):
            tasks = []
            today = datetime.date.today()
            lines = text.splitlines()
            for i, line in enumerate(lines):
                match = re.match(r'^(\s*-\s?\[([\sxX])\]\s*)(.*)', line)
                if match:
                    prefix, is_done, raw_text = match.group(1), match.group(2).lower() == 'x', match.group(3)
                    prio_match = re.search(r'#p([123])', raw_text)
                    br_match = re.search(r'#blocked:\s*([^#@\n]+)', raw_text)
                    dep_match = re.search(r'#dep:\s*([^#@\n]+)', raw_text)
                    due_match = re.search(r'@(\d{4}-\d{2}-\d{2})', raw_text)
                    # Extract description from parentheses at the end
                    desc_match = re.search(r'\(([^)]+)\)\s*$', raw_text)
                    
                    prio = int(prio_match.group(1)) if prio_match else 4
                    br = br_match.group(1).strip() if br_match else None
                    dr = dep_match.group(1).strip() if dep_match else None
                    desc_val = desc_match.group(1).strip() if desc_match else ""
                    
                    dv, ov = None, False
                    if due_match:
                        try:
                            dv = datetime.datetime.strptime(due_match.group(1), "%Y-%m-%d").date()
                            if dv < today and not is_done: ov = True
                        except: pass
                    
                    ct = raw_text
                    for m in [prio_match, br_match, dep_match, due_match, desc_match]:
                        if m: ct = ct.replace(m.group(0), '')
                    
                    tasks.append({
                        'line_idx': i, 'is_done': is_done, 'clean_text': ct.strip(), 
                        'raw_text': raw_text, 'prio': prio, 
                        'blocked': br, 'dep': dr, 'desc': desc_val,
                        'due': due_match.group(1) if due_match else None, 
                        'overdue': ov, 'is_archived': archived
                    })
            return tasks

        tasks = extract_tasks(active_part)
        if self.show_archived_t:
            tasks += extract_tasks(archive_part, archived=True)
            
        tasks.sort(key=lambda x: (x['is_archived'], x['is_done'], x['prio'], 0 if x['overdue'] else (1 if x['due'] else 2), x['due'] or "9999-12-31", x['line_idx']))
        return tasks

    def move_task(self, idx, direction):
        all_p = self.projects + self.archived_projects
        p = all_p[self.active_idx]
        if not p['path'] or not p['path'].exists(): return
        lines = p['path'].read_text(encoding='utf-8').splitlines()
        task_indices = [i for i, l in enumerate(lines) if re.match(r'^\s*-\s?\[[\sxX]\]', l)]
        try:
            curr_pos = task_indices.index(idx)
            new_pos = curr_pos + direction
            if 0 <= new_pos < len(task_indices):
                swap_idx = task_indices[new_pos]
                lines[idx], lines[swap_idx] = lines[swap_idx], lines[idx]
                p['path'].write_text("\n".join(lines), encoding='utf-8')
                self.refresh_projects(); self.render_sidebar.refresh(); self.render_tasks.refresh()
        except ValueError: pass

    def archive_project(self, idx=None):
        target_idx = idx if idx is not None else self.active_idx
        p = self.projects[target_idx]
        if p['name'] == "Empty_Portfolio" or p.get('is_archived'): return
        
        archive_root = Path(CONFIG["PROJECTS_ROOT"]) / "_Archive_2026"
        archive_root.mkdir(exist_ok=True)
        target_dir = archive_root / p['name']
        try:
            if target_dir.exists():
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M")
                target_dir = archive_root / f"{p['name']}_{ts}"
            os.rename(p['dir'], target_dir)
            ui.notify(f"Archived {p['name']}")
            self.active_idx = 0
            self.refresh_projects()
            self.render_sidebar.refresh(); self.render_tasks.refresh()
            asyncio.create_task(self.update_project_summary())
        except Exception as e: ui.notify(f"Error: {e}", type="negative")

    async def apply_refactor(self):
        all_p = self.projects + self.archived_projects
        p = all_p[self.active_idx]
        if self.refactor_content and "model is not available" not in self.refactor_content:
            p['path'].write_text(self.refactor_content, encoding='utf-8')
            ui.notify("Changes saved", type="positive")
            cache_key = (p['name'], "Summary", get_content_hash(p['path']))
            if cache_key in self.ai_cache: del self.ai_cache[cache_key]
            await self.update_project_summary()
            self.refresh_projects()
            self.render_sidebar.refresh()
            self.render_tasks.refresh()
            self.refactor_content = "Refactor applied."
            if hasattr(self, 'refactor_dialog'): self.refactor_dialog.close()

    async def discard_refactor(self):
        self.refactor_content = "Refactor discarded."
        ui.notify("Refactor discarded", type="warning")

    async def apply_config(self):
        global CONFIG
        CONFIG["PROJECTS_ROOT"] = self.c_root
        CONFIG["GLOBAL_MODEL_CMD"] = self.c_model
        CONFIG["MODEL_PREFS"] = self.model_prefs
        try: CONFIG["WIP_LIMIT"] = int(self.c_wip)
        except ValueError: pass
        save_config(CONFIG)
        ui.notify("Configuration saved", type="positive")
        self.refresh_projects(); self.render_sidebar.refresh()

    def update_file_line(self, line_idx, new_line_content):
        all_p = self.projects + self.archived_projects
        p = all_p[self.active_idx]
        if not p['path'] or not p['path'].exists(): return
        lines = p['path'].read_text(encoding='utf-8').splitlines()
        if 0 <= line_idx < len(lines):
            lines[line_idx] = new_line_content
            p['path'].write_text("\n".join(lines), encoding='utf-8')
            self.refresh_projects(); self.render_sidebar.refresh(); self.render_tasks.refresh()

    async def update_project_summary(self, force=False):
        all_p = self.projects + self.archived_projects
        p = all_p[self.active_idx]
        if not p['path'] or not p['path'].exists(): 
            self.project_summary = "No notes available."; self.render_project_summary.refresh(); return
        
        content = p['path'].read_text(encoding='utf-8', errors='ignore')
        
        # 1. Try to extract existing summary from file
        summary_match = re.search(r'## PROJECT SUMMARY\n(.*?)(?=\n##|$)', content, re.DOTALL)
        existing_summary = summary_match.group(1).strip() if summary_match else None
        
        # 2. Decide whether to use existing or generate new
        if not force and existing_summary:
            self.project_summary = existing_summary
            self.render_project_summary.refresh()
            return

        # 3. Generate new summary
        self.project_summary = "⏳ Thinking..."; self.render_project_summary.refresh()
        
        # Strip existing summary and archive from notes before sending to AI to keep context clean
        clean_notes = content
        if "## PROJECT SUMMARY" in clean_notes:
            clean_notes = re.sub(r'## PROJECT SUMMARY\n(.*?)(?=\n##|$)', '', clean_notes, flags=re.DOTALL)
        if "## ARCHIVE" in clean_notes:
            clean_notes = clean_notes.split("## ARCHIVE")[0]
            
        prompt = f"Summarize these project notes into a concise overview:\n\n{clean_notes}"
        mode = self.model_prefs.get("Summary", "local")
        engine_func = AIEngine.run_local if mode == "local" else AIEngine.run_copilot
        
        res = await run.io_bound(engine_func, prompt)
        new_summary = res or "Summary unavailable."
        
        # 4. Save to file
        summary_section = f"## PROJECT SUMMARY\n{new_summary}\n"
        if "## PROJECT SUMMARY" in content:
            new_content = re.sub(r'## PROJECT SUMMARY\n(.*?)(?=\n##|$)', f"## PROJECT SUMMARY\n{new_summary}", content, flags=re.DOTALL)
        else:
            # Insert before ARCHIVE or at end
            if "## ARCHIVE" in content:
                parts = content.split("## ARCHIVE", 1)
                new_content = f"{parts[0].strip()}\n\n{summary_section}\n## ARCHIVE{parts[1]}"
            else:
                new_content = f"{content.strip()}\n\n{summary_section}"
        
        p['path'].write_text(new_content, encoding='utf-8')
        self.project_summary = new_summary
        self.render_project_summary.refresh()

    @ui.refreshable
    def render_project_summary(self):
        with ui.column().classes('w-full bg-[#161b22] border-t border-[#30363d] mt-auto shrink-0 p-4'):
            with ui.row().classes('w-full justify-between items-center mb-2'):
                ui.label('PROJECT SUMMARY').classes('text-header-section text-blue-400')
                ui.button(icon='refresh', on_click=lambda: self.update_project_summary(force=True)).props('flat dense size=xs color=gray')
            with ui.scroll_area().classes('w-full h-80'): 
                ui.markdown(str(self.project_summary)).classes('text-[13px] text-blue-100 leading-relaxed')

    def toggle_task(self, idx, state):
        all_p = self.projects + self.archived_projects
        p = all_p[self.active_idx]; lines = p['path'].read_text(encoding='utf-8').splitlines()
        line = lines[idx]; is_done = bool(re.search(r'\[[xX]\]', line))
        lines[idx] = re.sub(r'\[[xX]\]', '[ ]', line, count=1) if is_done else re.sub(r'\[\s\]', '[x]', line, count=1)
        p['path'].write_text("\n".join(lines), encoding='utf-8')
        self.refresh_projects(); self.render_sidebar.refresh(); self.render_tasks.refresh()

    def archive_task(self, idx):
        all_p = self.projects + self.archived_projects
        p = all_p[self.active_idx]; lines = p['path'].read_text(encoding='utf-8').splitlines()
        tc = lines.pop(idx)
        if not any("## ARCHIVE" in l for l in lines): lines.append("\n## ARCHIVE")
        lines.append(f"{tc} ({datetime.datetime.now().strftime('%Y-%m-%d')})")
        p['path'].write_text("\n".join(lines), encoding='utf-8')
        self.refresh_projects(); self.render_sidebar.refresh(); self.render_tasks.refresh()

    def add_new_task(self):
        t = self.new_task_input.value.strip()
        all_p = self.projects + self.archived_projects
        p = all_p[self.active_idx]
        if t and p['path']:
            line = f"\n- [ ] {t}"
            with open(p['path'], "a", encoding="utf-8") as f: f.write(line)
            self.new_task_input.value = ""
            self.refresh_projects(); self.render_sidebar.refresh(); self.render_tasks.refresh()

    async def run_ai_tool(self, name, template, input_req=False, force=False):
        all_p = self.projects + self.archived_projects
        p = all_p[self.active_idx]
        c_hash = get_content_hash(p['path'])
        cache_key = (p['name'], name, c_hash)
        if not force and cache_key in self.ai_cache:
            res = self.ai_cache[cache_key]
        else:
            topic = ""
            if input_req:
                topic = await self.prompt_text(name, "Focus:")
                if not topic: return
            self.processing_status = f"Running {name}..."; self.render_header_status.refresh()
            p_text = template.format(project=p['name'], topic=topic, notes=p['path'].read_text(errors='ignore'), all_notes="".join([pr['path'].read_text(errors='ignore') for pr in self.projects if pr['path']]))
            mode = self.model_prefs.get(name, "local")
            engine_func = AIEngine.run_local if mode == "local" else AIEngine.run_copilot
            res = await run.io_bound(engine_func, p_text)
            if "model is not available" not in res: self.ai_cache[cache_key] = res
            self.processing_status = ""; self.render_header_status.refresh()
        if name == "Refactor Notes":
            self.refactor_content = res; self.open_refactor_dialog()
        elif name == "Daily Roadmap":
            self.daily_content = res; self.open_daily_dialog()
        else:
            self.insights_content = f"### {name}\n\n{res}"; self.open_chat_dialog()

    @ui.refreshable
    def render_header_status(self):
        if self.processing_status:
            with ui.row().classes('items-center gap-2 text-yellow-400'): 
                ui.spinner(size='sm'); ui.label(self.processing_status).classes('text-xs font-bold')
        else: ui.label("").classes('hidden')

    @ui.refreshable
    def render_sidebar(self):
        with ui.column().classes('gap-1 p-2 w-full'):
            # Compact archived toggle at the top
            with ui.row().classes('w-full px-3 py-1 items-center justify-between border-b border-gray-800 mb-2'):
                ui.label('ARCHIVED PROJECTS').classes('text-[9px] text-gray-500 font-bold')
                ui.switch(value=self.show_archived_p).bind_value(self, 'show_archived_p').on('update:model-value', self.refresh_projects).props('dense size=xs')

            all_p = self.projects + self.archived_projects
            for i, pr in enumerate(all_p):
                act = (i == self.active_idx); cls = 'sidebar-active shadow-md' if act else 'hover:bg-[#21262d] text-gray-400'
                with ui.row().classes(f'w-full items-center p-3 sidebar-item cursor-pointer {cls} no-wrap overflow-hidden').on('click', lambda idx=i: self.switch_project_async(idx)):
                    with ui.column().classes('gap-0 flex-grow overflow-hidden'):
                        name_cls = f"text-sm truncate {'text-white' if act else ('text-red-400 font-bold' if pr['todos'] > int(self.c_wip) else 'text-gray-200')}"
                        ui.label(pr['name']).classes(name_cls)
                        ui.label(f"T:{pr['todos']} | {int(pr['progress'])}%").classes('text-[10px] opacity-70')
                    if not pr['is_archived']:
                        ui.button(icon='archive', on_click=lambda _, idx=i: self.archive_project(idx)).props('flat dense size=xs color=orange').on('click', lambda e: e.stopPropagation())
                    else:
                        ui.icon('history', size='14px').classes('text-gray-600')

    async def switch_project_async(self, idx):
        self.active_idx = idx; self.render_sidebar.refresh(); self.render_tasks.refresh(); self.render_project_summary.refresh(); await self.update_project_summary()

    @ui.refreshable
    def render_tasks(self):
        tasks = self.parse_tasks()
        with ui.column().classes('w-full h-full flex-col p-6 bg-[#161b22] rounded-2xl border border-[#30363d] overflow-hidden shadow-lg'):
            with ui.row().classes('w-full justify-between items-center mb-2'):
                ui.label('BACKLOG').classes('text-header-section text-blue-400 shrink-0')
                ui.checkbox('Show Archived Tasks', value=self.show_archived_t).bind_value(self, 'show_archived_t').on('update:model-value', self.render_tasks.refresh).classes('text-[10px] text-gray-500')
            with ui.row().classes('w-full mb-2 gap-2 shrink-0'):
                self.new_task_input = ui.input(placeholder='New task name...').classes('flex-grow text-sm').props('outlined dark dense rounded')
                ui.button(icon='add', on_click=self.add_new_task).props('round dense color=blue')
            with ui.scroll_area().classes('w-full flex-grow'):
                for t in tasks:
                    with ui.row().classes('w-full items-center justify-between p-2 bg-[#0d1117] rounded-xl border border-[#30363d] task-card cursor-pointer no-wrap overflow-hidden').on('click', lambda _, task=t: self.open_task_details(task)):
                        with ui.row().classes('items-center gap-3 flex-grow no-wrap overflow-hidden'):
                            cb = ui.checkbox(value=t['is_done']).props('color=blue-5').on('click', lambda e: e.stopPropagation())
                            cb.on('update:model-value', lambda e, idx=t['line_idx']: self.toggle_task(idx, e.args))
                            if t['prio'] <= 3:
                                colors = {1: 'bg-red-700 text-white', 2: 'bg-yellow-400 text-black', 3: 'bg-green-600 text-white'}
                                symbols = {1: 'H', 2: 'M', 3: 'L'}
                                ui.label(symbols[t['prio']]).classes(f'text-[10px] px-1.5 py-0.5 rounded font-black {colors[t["prio"]]}')
                            with ui.column().classes('gap-0 flex-grow overflow-hidden'):
                                ui.markdown(t['clean_text']).classes(f"{'text-gray-500 line-through' if t['is_done'] else 'text-gray-100'} text-sm truncate")
                        with ui.row().classes('gap-1 shrink-0 items-center px-1'):
                            ui.button(icon='expand_less', on_click=lambda _, idx=t['line_idx']: self.move_task(idx, -1)).props('flat dense size=xs color=gray').on('click', lambda e: e.stopPropagation())
                            ui.button(icon='expand_more', on_click=lambda _, idx=t['line_idx']: self.move_task(idx, 1)).props('flat dense size=xs color=gray').on('click', lambda e: e.stopPropagation())
                            if t['due']: ui.label(f'📅 {t["due"]}').classes(f"text-[10px] {'text-red-400 font-bold' if t['overdue'] else 'text-gray-400'}")
                            if t['blocked']: ui.icon('block', size='16px').classes('text-red-500').tooltip(f"Blocked by: {t['blocked']}")
                            if t['dep']: ui.icon('link', size='16px').classes('text-orange-500').tooltip(f"Depends on: {t['dep']}")
                            if t['is_archived']: ui.icon('history', size='16px').classes('text-gray-600').tooltip('Archived Task')

    async def open_task_details(self, task):
        with ui.dialog() as dialog, ui.card().classes('w-[1100px] h-[850px] bg-gray-900 border border-gray-700 p-8'):
            ui.label('Task Details').classes('text-xl font-bold text-white mb-4')
            with ui.column().classes('w-full h-full gap-4'):
                # FULL WIDTH TITLE
                desc_title = ui.input('Title', value=task['clean_text']).classes('w-full').props('outlined dark')
                
                # MASSIVE DESCRIPTION AREA
                desc_long = ui.textarea('Description', value=task['desc']).classes('w-full flex-grow').props('outlined dark autogrow')
                
                with ui.row().classes('w-full gap-4'):
                    block = ui.input('Blocker', value=task['blocked'] or '').classes('w-1/2').props('outlined dark dense')
                    dep = ui.input('Dependency', value=task['dep'] or '').classes('w-1/2').props('outlined dark dense')
                
                # METADATA ROW AT BOTTOM
                with ui.row().classes('w-full gap-4 items-center'):
                    prio_sel = ui.select({1: 'High', 2: 'Medium', 3: 'Low', 4: 'None'}, value=task['prio'], label='Priority').classes('w-48').props('outlined dark dense')
                    
                    with ui.input('Due Date', value=task['due'] or '').classes('w-64').props('outlined dark dense') as date_in:
                        with ui.menu() as menu: ui.date().bind_value(date_in).on('update:model-value', menu.close)
                        with date_in.add_slot('append'): ui.icon('edit_calendar').on('click', menu.open).classes('cursor-pointer')
            
            with ui.row().classes('w-full justify-between mt-auto pt-4'):
                ui.button('Archive', on_click=lambda: self.archive_task(task['line_idx']) or dialog.submit(None)).props('flat color=orange')
                ui.button('Save', on_click=lambda: dialog.submit('save')).props('color=blue px-8')
        if await dialog == 'save':
            nl = f"- [{'x' if task['is_done'] else ' '}] {desc_title.value}"
            if prio_sel.value <= 3: nl += f" #p{prio_sel.value}"
            if date_in.value: nl += f' @{date_in.value}'
            if block.value.strip(): nl += f" #blocked: {block.value.strip()}"
            if dep.value.strip(): nl += f" #dep: {dep.value.strip()}"
            if desc_long.value.strip(): nl += f" ({desc_long.value.strip()})"
            self.update_file_line(task['line_idx'], nl)

    def open_chat_dialog(self):
        with ui.dialog() as dialog, ui.card().classes('w-[98vw] max-w-none h-[94vh] bg-gray-900 border border-gray-700'):
            with ui.row().classes('w-full justify-between items-center mb-2 px-4'):
                ui.label('AI Chat').classes('text-xl font-bold text-white')
                with ui.row().classes('items-center gap-2'):
                    ui.select(['local', 'cloud'], label='Engine', value=self.model_prefs.get('Chat', 'local')).bind_value(self, 'ai_mode').props('dense dark outlined')
                    ui.button(icon='refresh', on_click=lambda: self.run_ai_tool("Chat", "{notes}", force=True)).props('flat color=gray')
            with ui.scroll_area().classes('w-full flex-grow p-8 bg-black/20 rounded'):
                ui.markdown(self.insights_content or "No chat history.").classes('text-standard text-gray-100')
            ui.button('Close', on_click=dialog.close).props('flat color=blue mt-4 ml-4')
        dialog.open()

    def open_daily_dialog(self):
        with ui.dialog() as dialog, ui.card().classes('w-[98vw] max-w-none h-[94vh] bg-gray-900 border border-gray-700'):
            with ui.row().classes('w-full justify-between items-center mb-2 px-4'):
                ui.label('Daily Roadmap').classes('text-xl font-bold text-white')
                ui.button(icon='refresh', on_click=lambda: self.run_ai_tool('Daily Roadmap', 'Daily roadmap:\n{all_notes}', force=True)).props('flat color=gray')
            with ui.scroll_area().classes('w-full flex-grow p-8 bg-black/20 rounded'):
                ui.markdown(self.daily_content).classes('text-standard text-gray-100')
            ui.button('Close', on_click=dialog.close).props('flat color=blue mt-4 ml-4')
        dialog.open()

    def open_refactor_dialog(self):
        with ui.dialog() as self.refactor_dialog, ui.card().classes('w-[98vw] max-w-none h-[94vh] bg-gray-900 border border-gray-700'):
            with ui.row().classes('w-full justify-between items-center mb-2 px-4'):
                ui.label('Refactor Preview').classes('text-xl font-bold text-white')
                ui.button(icon='refresh', on_click=lambda: self.run_ai_tool('Refactor Notes', 'Refactor:\n{notes}', force=True)).props('flat color=gray')
            with ui.scroll_area().classes('w-full flex-grow border border-gray-700 p-8 rounded'):
                ui.markdown(self.refactor_content).classes('text-standard text-gray-100')
            with ui.row().classes('w-full justify-end gap-4 mt-4 mr-4'):
                ui.button('Discard', on_click=lambda: self.discard_refactor() or self.refactor_dialog.close()).props('flat color=red')
                ui.button('Accept & Save', on_click=self.apply_refactor).props('color=green')
        self.refactor_dialog.open()

    def open_config_dialog(self):
        with ui.dialog() as dialog, ui.card().classes('w-[600px] bg-gray-900 border border-gray-700 p-8'):
            ui.label('Configuration').classes('text-xl font-bold text-white mb-6')
            with ui.column().classes('w-full gap-4'):
                ui.input('Projects Root', value=self.c_root).bind_value(self, 'c_root').props('outlined dark')
                ui.input('Global Model Command', value=self.c_model).bind_value(self, 'c_model').props('outlined dark')
                ui.input('WIP Limit (Red Alert)', value=self.c_wip).bind_value(self, 'c_wip').props('outlined dark')
                ui.label('MODEL PREFERENCES').classes('text-header-section text-blue-400 mt-4')
                with ui.grid(columns=2).classes('w-full gap-4'):
                    for tool in ["Summary", "Chat", "Daily Roadmap", "Refactor Notes", "Executive", "Tech Plan", "Health", "Risks"]:
                        ui.select(['local', 'cloud'], label=tool, value=self.model_prefs.get(tool, 'local')).bind_value(self.model_prefs, tool).props('dense dark outlined')
            ui.button('Save & Apply', on_click=lambda: self.apply_config() or dialog.close()).props('color=blue w-full mt-8')
        dialog.open()

    async def submit_prompt(self):
        pr = self.cmd_input.value.strip()
        if not pr:
            return
        self.cmd_input.value = ''
        self.processing_status = 'Thinking...'
        self.render_header_status.refresh()
        p = (self.projects + self.archived_projects)[self.active_idx]
        ctx = f"Project: {p['name']}\nNotes: {p['path'].read_text()}\nPrompt: {pr}"
        
        mode = self.model_prefs.get("Chat", "local")
        engine_func = AIEngine.run_local if mode == "local" else AIEngine.run_copilot
        
        res = await run.io_bound(engine_func, ctx)
        self.insights_content = res
        self.processing_status = ''
        self.render_header_status.refresh()
        self.open_chat_dialog()

    async def prompt_text(self, title, message, default=''):
        with ui.dialog() as dialog, ui.card().classes('w-96 bg-gray-900 border border-gray-700'):
            ui.label(title).classes('text-lg font-bold text-white'); ui.label(message).classes('text-xs text-gray-400'); i = ui.input(value=default).classes('w-full').props('outlined dark')
            ui.button('Confirm', on_click=lambda: dialog.submit(i.value)).props('color=blue w-full')
        return await dialog

    def setup_ui(self):
        ui.dark_mode().enable()
        ui.add_head_html('<style>body { background-color: #0d1117; font-family: Inter, sans-serif; overflow: hidden; }.sidebar-active { background-color: #1f6feb !important; }.task-card:hover { border-color: #58a6ff !important; }.text-standard { font-size: 14px !important; }.text-header-section { font-size: 10px !important; font-weight: 700; letter-spacing: 0.1em; }::-webkit-scrollbar { width: 8px; height: 0px; }::-webkit-scrollbar-thumb { background: #30363d; border-radius: 4px; }.full-height-tasks { height: calc(100vh - 160px) !important; }</style>')
        with ui.header().classes('p-3 bg-[#161b22] border-b border-[#30363d] no-wrap items-center justify-between'):
            with ui.row().classes('items-center gap-4 shrink-0'):
                ui.button(icon='menu', on_click=lambda: self.drawer.toggle()).props('flat color=white'); ui.label('TPM COMMAND CENTER').classes('text-lg font-bold text-white')
            with ui.row().classes('items-center gap-1'):
                for tool, prmt in [('EXECUTIVE', 'ROI:\n{notes}'), ('TECH PLAN', 'Plan:\n{notes}'), ('HEALTH', 'Health:\n{notes}'), ('RISKS', 'Risks:\n{notes}')]:
                    ui.button(tool, on_click=lambda t=tool, p=prmt: self.run_ai_tool(t.title(), p, input_req=(t == 'TECH PLAN'))).props('flat color=blue dense size=sm')
                ui.button('CHAT', on_click=self.open_chat_dialog).props('flat color=blue dense size=sm')
                ui.button('DAILY', on_click=lambda: self.run_ai_tool('Daily Roadmap', 'Daily roadmap:\n{all_notes}')).props('flat color=blue dense size=sm')
                ui.button('REFACTOR', on_click=lambda: self.run_ai_tool('Refactor Notes', 'Refactor these notes:\n{notes}')).props('flat color=purple dense size=sm')
                ui.button(icon='settings', on_click=self.open_config_dialog).props('flat color=gray dense size=sm')
                self.render_header_status()
        self.drawer = ui.left_drawer(value=True).props('width=500').classes('bg-[#161b22] p-0 flex flex-col')
        with self.drawer: 
            with ui.column().classes('w-full h-full no-wrap'):
                with ui.scroll_area().classes('w-full flex-grow'): self.render_sidebar()
                self.render_project_summary()
        with ui.column().classes('w-full flex-grow p-4 bg-[#0d1117] overflow-hidden min-h-0'):
            with ui.column().classes('w-full h-full full-height-tasks'): self.render_tasks()
        with ui.footer().classes('bg-[#161b22] border-t border-[#30363d] p-3 shrink-0'):
            with ui.row().classes('w-full items-center gap-4'):
                self.ai_toggle = ui.toggle({'local': 'LOCAL', 'cloud': 'CLOUD'}, value='local').bind_value(self, 'ai_mode').props('rounded dense size=sm')
                self.cmd_input = ui.input(placeholder='Ask AI...').classes('flex-grow text-sm').props('outlined dark dense rounded'); ui.button(icon='send', on_click=self.submit_prompt).props('elevated color=blue')

if __name__ in {"__main__", "__mp_main__"}:
    WebTPM(); ui.query('.q-page').classes('h-screen flex flex-col'); ui.query('.q-page-container').classes('h-screen overflow-hidden'); ui.run(title="TPM GUI", port=8080, dark=True, reload=False)
