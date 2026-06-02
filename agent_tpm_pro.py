import os
import subprocess
import datetime
import re
import sys
import threading
import time
from pathlib import Path

# --- TERMINAL HISTORY & INTERACTIVE EDITING ---
try:
    import readline
    histfile = os.path.join(os.path.expanduser("~"), ".tpm_agent_history")
    try:
        readline.read_history_file(histfile)
    except FileNotFoundError:
        pass
    import atexit
    atexit.register(readline.write_history_file, histfile)
    
    def set_input_hook(text):
        """Pre-fills the terminal input line for editing."""
        readline.set_startup_hook(lambda: readline.insert_text(text))
        
    def clear_input_hook():
        """Clears the pre-fill hook after use."""
        readline.set_startup_hook(None)
except ImportError:
    readline = None
    def set_input_hook(text): pass
    def clear_input_hook(): pass

# --- RICH TUI COMPONENTS ---
try:
    from rich.console import Console
    from rich.layout import Layout
    from rich.panel import Panel
    from rich.table import Table
    from rich.markdown import Markdown
    from rich.text import Text
    from rich.columns import Columns
    from rich.spinner import Spinner
    from rich.live import Live
    from rich import box
except ImportError:
    print("CRITICAL ERROR: 'rich' library not found. Install: pip install rich")
    sys.exit(1)

# --- GLOBAL SETTINGS ---
PROJECTS_ROOT = "projects"
LOCAL_MODEL = "llama3.2:3b"
WIP_LIMIT = 8
console = Console()

# --- ENTERPRISE AI ENGINE ---
class AIEngine:
    """Analytical engine with high-fidelity prompt engineering for Data Engineering."""
    
    @staticmethod
    def run_local(prompt, status_callback=None):
        """Executes local LLaMA model with a high timeout for large context windows."""
        if status_callback: status_callback("Processing with Local AI...")
        try:
            res = subprocess.run(['ollama', 'run', LOCAL_MODEL, prompt], 
                                capture_output=True, text=True, encoding='utf-8', timeout=60)
            if res.returncode != 0:
                return f"⚠️ Ollama Error: {res.stderr}"
            return res.stdout.strip()
        except subprocess.TimeoutExpired:
            return "⚠️ AI Timeout: Local model is processing a large context window."
        except Exception as e:
            return f"⚠️ AI Engine Exception: {str(e)}"
        finally:
            if status_callback: status_callback("")

    @staticmethod
    def run_copilot(prompt, status_callback=None):
        """Executes GitHub Copilot CLI for executive-level synthesis with Ollama fallback."""
        if status_callback: status_callback("Checking Copilot...")
        try:
            # Check if 'gh' command exists
            subprocess.run(['gh', '--version'], capture_output=True, check=True)
            
            if status_callback: status_callback("Processing with Copilot...")
            res = subprocess.run(['gh', 'copilot', 'chat', '-p', prompt], 
                                capture_output=True, text=True, encoding='utf-8', timeout=60)
            if res.returncode != 0:
                # Fallback if gh exists but copilot extension is missing or auth fails
                return AIEngine.run_local(f"[Copilot Fallback] {prompt}", status_callback)
            return res.stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            # Fallback if 'gh' is not installed
            return AIEngine.run_local(f"[Executive Request] {prompt}", status_callback)
        except Exception as e:
            return f"⚠️ Copilot Exception: {str(e)}"
        finally:
            if status_callback: status_callback("")

# --- TPM MISSION CONTROL ---
class AgentTUI:
    def __init__(self):
        self.log_content = "### TPM V8.8 Ready\nWelcome. Use `/id#` to switch contexts. Type `/help` for commands."
        self.active_idx = 0
        self.projects = []
        self.session_buffer = [] 
        self.processing_status = ""
        self.refresh_projects()

    def set_status(self, msg):
        self.processing_status = msg
        self.render_screen()

    def refresh_projects(self):
        """Scans metadata: Tasks, Urgent items, Blockers, and Progress."""
        root = Path(PROJECTS_ROOT)
        root.mkdir(exist_ok=True)
        self.projects = []
        dirs = sorted([d for d in root.iterdir() if d.is_dir() and not d.name.startswith('_')])
        
        for d in dirs:
            n_path = d / "notes.md"
            t_count, b_count, u_count, done_count, total_count = 0, 0, 0, 0, 0
            if n_path.exists():
                try:
                    content = n_path.read_text(encoding='utf-8', errors='ignore')
                    lines = content.splitlines()
                    task_lines = [l for l in lines if re.match(r'^\s*-\s?\[[\sxX]\]', l)]
                    total_count = len(task_lines)
                    done_count = len([l for l in task_lines if re.search(r'\[[xX]\]', l)])
                    
                    # Count open tasks: lines matching task pattern but not containing #blocked
                    t_count = len([l for l in task_lines if re.match(r'^\s*-\s?\[\s\]', l) and "#blocked" not in l])
                    # Count blockers: any line containing #blocked
                    b_count = len([l for l in lines if "#blocked" in l])
                    # Count urgency tags
                    u_count = len(re.findall(r'#urgent|#high|\[!\]', content, re.IGNORECASE))
                except Exception:
                    pass
            
            progress = (done_count / total_count * 100) if total_count > 0 else 0
            self.projects.append({
                "name": d.name, 
                "todos": t_count, 
                "blockers": b_count, 
                "urgent": u_count, 
                "progress": progress,
                "path": n_path,
                "dir": d
            })
        
        if not self.projects:
            self.projects = [{"name": "Empty_Portfolio", "todos": 0, "blockers": 0, "urgent": 0, "progress": 0, "path": None, "dir": None}]

    def archive_project(self):
        """Moves the entire active project directory to the archive folder."""
        p = self.projects[self.active_idx]
        if p['name'] == "Empty_Portfolio": return "⚠️ Cannot archive an empty portfolio."
        
        archive_root = Path(PROJECTS_ROOT) / "_Archive_2026"
        archive_root.mkdir(exist_ok=True)
        
        target_dir = archive_root / p['name']
        try:
            if target_dir.exists():
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M")
                target_dir = archive_root / f"{p['name']}_{ts}"
            
            os.rename(p['dir'], target_dir)
            self.active_idx = 0
            self.refresh_projects()
            return f"📦 **Project {p['name']} archived successfully.**"
        except Exception as e:
            return f"⚠️ Archiving Error: {str(e)}"

    def trigger_auto_summary(self, manual=False):
        """Synthesizes context changes before switching projects or on demand."""
        if not self.session_buffer: 
            return "" if not manual else "No session data to recap."
        
        p_name = self.projects[self.active_idx]['name']
        updates = "\n".join(self.session_buffer)
        prompt = (f"Act as a Technical Project Manager. Summarize these updates for project '{p_name}' "
                  f"into two professional action-oriented bullet points. "
                  f"CRITICAL: Keep it extremely brief (max 4 lines) to fit the UI:\n\n{updates}"
                  f"Return only output without additional text decorators that prompt produces.")
        
        summary = AIEngine.run_local(prompt, self.set_status)
        self.session_buffer = [] 
        return f"\n\n**🤖 {'MANUAL ' if manual else ''}SUMMARY:**\n{summary}"

    def get_task_list_markdown(self):
        """Renders the top workspace view with precise task numbering and due dates."""
        p = self.projects[self.active_idx]
        if not p['path'] or not p['path'].exists(): 
            return "⚠️ No note file found for this project."
        
        lines = p['path'].read_text(encoding='utf-8', errors='ignore').splitlines()
        tasks = [(i, l) for i, l in enumerate(lines) if re.match(r'^\s*-\s?\[[\sxX]\]', l)]
        
        if not tasks: 
            return f"### {p['name']}\nBacklog is empty."
        
        today = datetime.date.today()
        res = f"### ACTIVE BACKLOG: {p['name']}\n\n"
        for i, (orig_idx, line) in enumerate(tasks):
            # Parse Due Date
            due_match = re.search(r'@(\d{4}-\d{2}-\d{2})', line)
            due_str = ""
            if due_match:
                try:
                    due_date = datetime.datetime.strptime(due_match.group(1), "%Y-%m-%d").date()
                    clean_line = line.replace(due_match.group(0), "").strip()
                    if due_date < today and "[x]" not in line.lower():
                        due_str = f" [bold red]📅 OVERDUE: {due_match.group(1)}[/]"
                    else:
                        due_str = f" [dim]📅 Due: {due_match.group(1)}[/]"
                    line = clean_line
                except ValueError: pass
            
            res += f"{i+1}. {line}{due_str}\n\n"
        return res

    def get_command_map(self):
        """Returns context-aware and properly documented command map."""
        global_map = "[cyan]Global:[/cyan] /id# | /daily | /list | /summary | /archive | /q"
        task_map = "[cyan]Tasks:[/cyan]  /add [text] | /done# | /edit# | /block# [txt] | /unblock# | /archive#"
        ai_map = "[cyan]AI:[/cyan]     /exec | /plan [txt] | /deps | /health | /risks | /refactor"
        return f"{global_map}\n{task_map}\n{ai_map}"

    def handle_command(self, cmd):
        """Core Router: Explicit and robust handling of all TPM activities."""
        
        # 0. PROJECT OPERATIONS
        if cmd == "/archive":
            return self.archive_project()

        # 1. NAVIGATION & HELP
        m_id = re.match(r'^/id(\d+)$', cmd)
        if m_id:
            try:
                num = int(m_id.group(1)) - 1
                if 0 <= num < len(self.projects):
                    sum_text = self.trigger_auto_summary()
                    self.active_idx = num
                    return f"📂 **Context:** {self.projects[self.active_idx]['name']}\n{sum_text}"
                return f"⚠️ Error: ID {num+1} out of bounds."
            except Exception as e:
                return f"⚠️ Navigation Error: {str(e)}"

        if cmd == "/help":
            return self.get_command_map()

        p = self.projects[self.active_idx]
        p_path = p['path']
        if not p_path: 
            return "⚠️ No active file for operations."
        
        ts = datetime.datetime.now().strftime("%H:%M")
        
        # Load tasks for indexing operations
        try:
            lines = p_path.read_text(encoding='utf-8').splitlines() if p_path.exists() else []
            idx_map = [i for i, l in enumerate(lines) if re.match(r'^\s*-\s?\[[\sxX]\]', l)]
        except Exception as e:
            return f"⚠️ File Read Error: {str(e)}"

        # 2. TASK OPERATIONS
        m_done = re.match(r'^/done(\d+)$', cmd)
        m_edit = re.match(r'^/edit(\d+)$', cmd)
        m_update = re.match(r'^/update(\d+)\s+(.+)$', cmd)
        m_block_task = re.match(r'^/block(\d+)\s+(.+)$', cmd)
        m_unblock_task = re.match(r'^/unblock(\d+)$', cmd)
        m_archive_task = re.match(r'^/archive(\d+)$', cmd)

        if m_done:
            try:
                num = int(m_done.group(1)) - 1
                if 0 <= num < len(idx_map):
                    ln = idx_map[num]
                    if "[ ]" in lines[ln]:
                        lines[ln] = lines[ln].replace("[ ]", "[x]", 1)
                    else:
                        lines[ln] = lines[ln].replace("[x]", "[ ]", 1)
                    p_path.write_text("\n".join(lines), encoding='utf-8')
                    self.session_buffer.append(f"Toggled completion status for task {num+1}.")
                    return f"✅ **Task {num+1} status updated.**"
                return "⚠️ Task ID not found."
            except Exception as e:
                return f"⚠️ Execution Error: {str(e)}"

        elif m_edit:
            try:
                num = int(m_edit.group(1)) - 1
                if 0 <= num < len(idx_map):
                    ln = idx_map[num]
                    match = re.match(r'^(\s*-\s?\[[\sxX]\]\s*)(.*)', lines[ln])
                    if match:
                        current_desc = match.group(2)
                        if readline:
                            set_input_hook(f"/update{num+1} {current_desc}")
                        return (f"📝 **Editing Task {num+1}.** Use `/update{num+1} [text]`")
                    return "⚠️ Could not parse task description."
                return "⚠️ Task ID not found."
            except Exception as e:
                return f"⚠️ Execution Error: {str(e)}"

        elif m_update:
            try:
                num = int(m_update.group(1)) - 1
                new_txt = m_update.group(2)
                if 0 <= num < len(idx_map):
                    ln = idx_map[num]
                    prefix = re.match(r'^(\s*-\s?\[[\sxX]\]\s*)', lines[ln]).group(1)
                    lines[ln] = f"{prefix}{new_txt}"
                    p_path.write_text("\n".join(lines), encoding='utf-8')
                    self.session_buffer.append(f"Updated description for task {num+1}.")
                    return f"✨ **Task {num+1} updated successfully.**"
                return "⚠️ Task ID not found."
            except Exception as e:
                return f"⚠️ Execution Error: {str(e)}"

        elif m_block_task:
            try:
                num = int(m_block_task.group(1)) - 1
                reason = m_block_task.group(2)
                if 0 <= num < len(idx_map):
                    lines[idx_map[num]] += f" #blocked: {reason}"
                    p_path.write_text("\n".join(lines), encoding='utf-8')
                    self.session_buffer.append(f"Marked task {num+1} as blocked.")
                    return f"🚨 **Task {num+1} blocked:** {reason}"
                return "⚠️ Task ID not found."
            except Exception as e:
                return f"⚠️ Execution Error: {str(e)}"

        elif m_unblock_task:
            try:
                num = int(m_unblock_task.group(1)) - 1
                if 0 <= num < len(idx_map):
                    lines[idx_map[num]] = re.sub(r'\s*#blocked:.*', '', lines[idx_map[num]])
                    p_path.write_text("\n".join(lines), encoding='utf-8')
                    self.session_buffer.append(f"Removed blocker from task {num+1}.")
                    return f"🟢 **Task {num+1} unblocked.**"
                return "⚠️ Task ID not found."
            except Exception as e:
                return f"⚠️ Execution Error: {str(e)}"

        elif m_archive_task:
            try:
                num = int(m_archive_task.group(1)) - 1
                if 0 <= num < len(idx_map):
                    task_content = lines.pop(idx_map[num])
                    if not any("## ARCHIVE" in l for l in lines): 
                        lines.append("\n## ARCHIVE")
                    lines.append(f"{task_content} (archived: {ts})")
                    p_path.write_text("\n".join(lines), encoding='utf-8')
                    self.session_buffer.append(f"Archived task {num+1}.")
                    return f"📦 **Task {num+1} securely archived.**"
                return "⚠️ Task ID not found."
            except Exception as e:
                return f"⚠️ Execution Error: {str(e)}"

        # 3. AI STRATEGIC TOOLS
        elif cmd == "/daily":
            all_t = ""
            for proj in self.projects:
                if proj['path'] and proj['path'].exists():
                    all_t += f"\nPROJECT: {proj['name']}\n" + proj['path'].read_text(errors='ignore')
            prompt = (f"Act as a TPM. Review Data Engineering notes. Group by project, highlight #urgent. "
                      f"Max 10 lines total:\n{all_t}")
            res = AIEngine.run_local(prompt, self.set_status)
            return f"**🗓️ Daily Roadmap:**\n\n{res}"

        elif cmd == "/exec":
            prompt = (f"Executive report for {p['name']}. Focus on milestones and ROI. "
                      f"Max 10 lines:\n{p_path.read_text()}")
            res = AIEngine.run_copilot(prompt, self.set_status)
            return f"**📊 Executive Report:**\n\n{res}"
        
        elif cmd.startswith("/plan "):
            topic = cmd[6:]
            prompt = (f"Design technical implementation roadmap for '{topic}' in {p['name']}. "
                      f"Max 10 lines total, use short bullet points:\n{p_path.read_text()}")
            res = AIEngine.run_copilot(prompt, self.set_status)
            return f"**🗺️ Plan for '{topic}':**\n\n{res}"
        
        elif cmd == "/deps":
            prompt = (f"List external dependencies and technical blockers for {p['name']}. Max 8 lines:\n{p_path.read_text()}")
            res = AIEngine.run_local(prompt, self.set_status)
            return f"**🔗 Dependencies:**\n\n{res}"
        
        elif cmd == "/health":
            prompt = (f"Analyze project health for {p['name']} (WIP, blockers). Max 8 lines:\n{p_path.read_text()}")
            res = AIEngine.run_local(prompt, self.set_status)
            return f"**❤️ Health Check:**\n\n{res}"
        
        elif cmd == "/risks":
            prompt = (f"Identify top technical risks for {p['name']}. Max 3 bullets:\n{p_path.read_text()}")
            res = AIEngine.run_local(prompt, self.set_status)
            return f"**⚠️ Risk Assessment:**\n\n{res}"
        
        elif cmd == "/refactor":
            prompt = f"Refactor these project notes for {p['name']}. Clean markdown, group logically:\n{p_path.read_text()}"
            res = AIEngine.run_local(prompt, self.set_status)
            if "⚠️" not in res: 
                p_path.write_text(res)
                return "✨ **Notes successfully refactored and cleaned.**"
            return res

        # 4. UTILITIES & GLOBAL COMMANDS
        elif cmd == "/summary":
            return self.trigger_auto_summary(manual=True)

        elif cmd == "/list":
            res = "### FULL PORTFOLIO OVERVIEW:\n\n"
            for i, proj in enumerate(self.projects):
                status_icon = '🔴' if proj['blockers'] > 0 else '🟢'
                res += f"**{i+1}. {proj['name']}** | Progress: {int(proj['progress'])}% | Status: {status_icon}\n\n"
            return res

        elif cmd.startswith("/add "):
            task_text = cmd[5:]
            with open(p_path, "a", encoding="utf-8") as f: 
                f.write(f"\n- [ ] {task_text}")
            self.session_buffer.append(f"Added new task: {task_text}")
            return f"✅ **Task added.**"

        elif cmd.startswith("/search "):
            q = cmd[8:].lower()
            m = [f"- **{proj['name']}**" for proj in self.projects if proj['path'] and q in proj['path'].read_text(errors='ignore').lower()]
            return "### SEARCH RESULTS:\n\n" + ("\n".join(m) if m else "No matching notes found.")

        elif not cmd.startswith("/"):
            with open(p_path, "a", encoding="utf-8") as f: 
                f.write(f"\n> {cmd} ({ts})")
            self.session_buffer.append(f"Note logged: {cmd}")
            return f"📝 **General note logged.**"

        return f"Unknown command '{cmd}'. Type `/help` for Command Map."

    def make_display(self):
        """Constructs TUI with side-by-side columns for a high-density dashboard."""
        p = self.projects[self.active_idx]
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3), 
            Layout(name="main", ratio=1), 
            Layout(name="footer", size=3)
        )
        # Horizontal split: Portfolio (Left) | Tasks (Middle) | Insights (Right)
        layout["main"].split_row(
            Layout(name="side", size=30), 
            Layout(name="tasks_view", ratio=1),
            Layout(name="logs_view", ratio=1)
        )
        
        # Header with Progress
        prog_val = int(p['progress'])
        prog_color = "green" if prog_val > 70 else "yellow" if prog_val > 30 else "red"
        
        head_text = Text.assemble(
            (" TPM COMMAND CENTER ", "bold white on blue"),
            (" | ", "dim"),
            (f"Context: {p['name']}", "bold cyan"),
            (f" [{prog_val}%]", f"bold {prog_color}")
        )
        if self.processing_status:
            head_text.append(f" | ⏳ {self.processing_status}", style="bold yellow blink")
        
        layout["header"].update(Panel(head_text, style="white on #161b22", box=box.SQUARE))
        
        # Portfolio Sidebar (Simplified)
        table = Table(show_header=True, header_style="bold blue", box=None, expand=True, padding=(0, 1))
        table.add_column("ID", width=3, justify="right")
        table.add_column("Project", no_wrap=True)
        table.add_column("!", justify="center", width=1)
        
        for i, proj in enumerate(self.projects):
            is_act = (i == self.active_idx)
            style = "bold cyan" if is_act else "white"
            name = f"{proj['name']} ({int(proj['progress'])}%)"
            if proj['todos'] > WIP_LIMIT and not is_act: name = f"[red]{name}[/]"
            
            table.add_row(
                str(i + 1), 
                Text.from_markup(name, style=style), 
                "🔴" if proj['blockers'] > 0 else " "
            )
            
        layout["side"].update(Panel(table, title="[bold blue]Portfolio[/]", border_style="blue", box=box.ROUNDED))
        
        # Backlog & Insights (Side-by-Side)
        layout["tasks_view"].update(Panel(
            Markdown(self.get_task_list_markdown()), 
            title="[bold green]Active Backlog[/]", 
            border_style="green", 
            padding=(1, 1), 
            box=box.ROUNDED
        ))
        
        log_parts = [part.strip() for part in self.log_content.split('\n\n') if part.strip()]
        formatted_log = "\n\n".join(log_parts)
        
        layout["logs_view"].update(Panel(
            Markdown(formatted_log), 
            title="[bold yellow]Strategic Insights[/]", 
            border_style="yellow", 
            padding=(1, 1), 
            box=box.ROUNDED
        ))
        
        # Footer
        footer_text = "/id# | /daily | /exec | /plan | /archive | /add | /done# | /edit# | /q"
        layout["footer"].update(Panel(Text(footer_text, justify="center", style="dim"), box=box.SQUARE))
        
        return layout

    def render_screen(self):
        """Helper to immediately push layout changes (used for status updates)."""
        os.system('cls' if os.name == 'nt' else 'clear')
        console.print(self.make_display())

    def run(self):
        """Main event loop."""
        while True:
            self.render_screen()
            
            try:
                cmd_input = console.input("> ").strip()
                clear_input_hook()
            except EOFError: 
                break
            
            # STRICT EXIT CHECK
            if cmd_input.lower() in ["/q", "/exit"]:
                self.set_status("Generating final session summary...")
                summary = self.trigger_auto_summary()
                os.system('cls' if os.name == 'nt' else 'clear')
                if summary: 
                    console.print(Markdown(f"# SESSION RECAP\n{summary}"))
                    input("\nPress Enter to fully exit...")
                sys.exit(0)
                
            if cmd_input:
                self.log_content = self.handle_command(cmd_input)
                self.refresh_projects()

if __name__ == "__main__":
    AgentTUI().run()
