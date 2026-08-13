import datetime
import re
from typing import List, Tuple, Optional
from pathlib import Path
from models.task import Task

class MarkdownParser:
    @staticmethod
    def parse_tasks(content: str, show_archived: bool = False, project_path: Optional[Path] = None) -> List[Task]:
        """Parses all tasks from markdown content with metadata, tag, and section awareness using AST."""
        if not content:
            return []

        from markdown_it import MarkdownIt
        md = MarkdownIt()
        tokens = md.parse(content)
        lines = content.splitlines()

        tasks: List[Task] = []
        today = datetime.date.today()
        current_section = None
        in_tasks_section = False
        has_tasks_section = bool(re.search(r'^##+\s+Tasks', content, re.MULTILINE | re.IGNORECASE))
        
        for i, t in enumerate(tokens):
            if t.type == "heading_open":
                level = int(t.tag[1:])
                inline_tok = tokens[i+1]
                if inline_tok.type == "inline":
                    header_name = inline_tok.content.strip()
                    current_section = header_name
                    if level == 2:
                        in_tasks_section = "TASKS" in header_name.upper()
            
            elif t.type == "list_item_open" and t.map:
                start, end = t.map
                if start >= len(lines):
                    continue
                slice_lines = lines[start:end]
                if not slice_lines:
                    continue
                
                first_line = slice_lines[0]
                match = re.match(r'^(\s*-\s?\[([\sxX])\]\s*)(.*)', first_line)
                if match:
                    is_done = match.group(2).lower() == 'x'
                    raw_text = match.group(3)
                    body_lines = slice_lines[1:] if len(slice_lines) > 1 else None
                    
                    # Extract metadata tags from first line raw_text
                    prio_match = re.search(r'#p([123])', raw_text, re.IGNORECASE)
                    br_match = re.search(r'#blocked:\s*([^#@\n(]+)', raw_text, re.IGNORECASE)
                    dep_match = re.search(r'#dep:\s*([^#@\n(]+)', raw_text, re.IGNORECASE)
                    due_match = re.search(r'@(\d{4}-\d{2}-\d{2})', raw_text)
                    desc_match = re.search(r'\(([^)]+)\)\s*$', raw_text)
                    wip_match = re.search(r'#(?:in_progress|wip)\b', raw_text, re.IGNORECASE)

                    prio = int(prio_match.group(1)) if prio_match else 4
                    br = br_match.group(1).strip() if br_match else None
                    dr = dep_match.group(1).strip() if dep_match else None
                    desc_val = desc_match.group(1).strip() if desc_match else ""

                    due_str = due_match.group(1) if due_match else None
                    overdue = False
                    if due_str:
                        try:
                            dv = datetime.datetime.strptime(due_str, "%Y-%m-%d").date()
                            if dv < today and not is_done:
                                overdue = True
                        except Exception:
                            pass

                    clean_text = raw_text
                    for m in [prio_match, br_match, dep_match, due_match, desc_match, wip_match]:
                        if m:
                            clean_text = clean_text.replace(m.group(0), '')
                    clean_text = clean_text.strip()

                    is_archived = (current_section is not None and "ARCHIVE" in current_section.upper())

                    if is_archived and not show_archived:
                        continue

                    if not is_archived and has_tasks_section:
                        if not in_tasks_section and not (current_section and "TASKS" in current_section.upper()):
                            continue

                    import hashlib
                    task_id = hashlib.md5(f"{start}:{first_line.strip()}".encode('utf-8')).hexdigest()[:10]
                    
                    task = Task(
                        id=task_id,
                        line_start=start,
                        line_end=end,
                        clean_text=clean_text,
                        raw_text=raw_text,
                        is_done=is_done,
                        prio=prio,
                        blocked=br,
                        dep=dr,
                        desc=desc_val,
                        body_lines=body_lines,
                        due=due_str,
                        overdue=overdue,
                        is_archived=is_archived,
                        section=current_section,
                        project_path=project_path
                    )
                    tasks.append(task)

        # Sort tasks
        tasks.sort(key=lambda x: (
            x.is_archived,
            x.is_done,
            x.prio,
            0 if x.overdue else (1 if x.due else 2),
            x.due or "9999-12-31",
            x.line_start
        ))
        return tasks

    @staticmethod
    def calculate_stats(content: str) -> Tuple[int, int, int, float]:
        """Calculates accurate (todos, blockers, urgent, progress) metrics from parsed active tasks."""
        if not content:
            return 0, 0, 0, 0.0

        tasks = MarkdownParser.parse_tasks(content, show_archived=False)
        total = len(tasks)
        if total == 0:
            return 0, 0, 0, 0.0

        done = len([t for t in tasks if t.is_done])
        # Open work items: uncompleted and not blocked
        todos = len([t for t in tasks if not t.is_done and not t.blocked])
        # Blockers only count open uncompleted blocked tasks
        blockers = len([t for t in tasks if not t.is_done and t.blocked])
        # Urgent only counts open uncompleted #p1 tasks
        urgent = len([t for t in tasks if not t.is_done and t.prio == 1])
        prog = (done / total * 100.0) if total > 0 else 0.0

        return todos, blockers, urgent, prog

    @staticmethod
    def extract_summary(content: str) -> Optional[str]:
        """Extracts existing project summary if present, including multi-line paragraphs."""
        match = re.search(r'^##+\s+PROJECT SUMMARY\s*\n(.*?)(?=(?:\n##+|\Z))', content, re.DOTALL | re.IGNORECASE | re.MULTILINE)
        return match.group(1).strip() if match else None

    @staticmethod
    def extract_project_info(content: str) -> str:
        """Extracts multi-line project info context if present."""
        match = re.search(r'^#+\s+Project Info\s*\n(.*?)(?=(?:\n##+|\Z))', content, re.DOTALL | re.IGNORECASE | re.MULTILINE)
        return match.group(1).strip() if match else ""

    @staticmethod
    def add_task(content: str, task_text: str) -> str:
        """Appends a new task to the ## Tasks section safely without regex backslash corruption."""
        task_line = f"- [ ] {task_text.strip()}"
        if not content.strip():
            return f"## Tasks\n{task_line}\n"

        match = re.search(r'(^##+\s+Tasks.*?)((?=\n##+|\Z))', content, re.DOTALL | re.MULTILINE | re.IGNORECASE)
        if match:
            start, end = match.span()
            tasks_block = match.group(1).rstrip() + f"\n{task_line}\n"
            return content[:start] + tasks_block + content[end:]
        else:
            for section in ["## PROJECT SUMMARY", "## Project Summary", "## ARCHIVE", "## Archive"]:
                if section in content:
                    return content.replace(section, f"## Tasks\n{task_line}\n\n{section}", 1)
            return content.strip() + f"\n\n## Tasks\n{task_line}\n"

    @staticmethod
    def insert_subtasks(content: str, line_end: int, subtasks: List[str]) -> str:
        """Inserts generated subtasks immediately after parent task block."""
        lines = content.splitlines()
        if not (0 <= line_end <= len(lines)):
            return content

        formatted_subtasks = []
        for st in subtasks:
            st = st.strip()
            if st:
                if st.startswith("- ["):
                    formatted_subtasks.append(st)
                else:
                    formatted_subtasks.append(f"- [ ] {st}")
        new_lines = lines[:line_end] + formatted_subtasks + lines[line_end:]
        return "\n".join(new_lines) + "\n"

    @staticmethod
    def update_summary(content: str, summary_text: str) -> str:
        """Replaces or inserts the ## PROJECT SUMMARY section cleanly without accumulation."""
        summary_block = f"## PROJECT SUMMARY\n{summary_text.strip()}\n"
        match = re.search(r'^##+\s+PROJECT SUMMARY.*?(?=(?:\n##+|\Z))', content, re.DOTALL | re.MULTILINE | re.IGNORECASE)
        if match:
            start, end = match.span()
            return content[:start] + summary_block + content[end:]
        elif re.search(r'^##+\s+ARCHIVE', content, re.MULTILINE | re.IGNORECASE):
            parts = re.split(r'(^##+\s+ARCHIVE)', content, maxsplit=1, flags=re.MULTILINE | re.IGNORECASE)
            return f"{parts[0].strip()}\n\n{summary_block}\n{parts[1]}{parts[2]}"
        else:
            return f"{content.strip()}\n\n{summary_block}"

    @staticmethod
    def archive_task(content: str, line_start: int, line_end: int) -> Tuple[str, Optional[str]]:
        """Removes a task block from its current location and moves it to ## ARCHIVE."""
        lines = content.splitlines()
        if not (0 <= line_start < len(lines) and line_start < line_end <= len(lines)):
            return content, None

        task_lines = lines[line_start:line_end]
        del lines[line_start:line_end]

        today_str = datetime.date.today().strftime('%Y-%m-%d')
        task_lines[0] = f"{task_lines[0]} (Archived: {today_str})"
        archived_entry = "\n".join(task_lines)
        new_content = "\n".join(lines)

        archive_match = re.search(r'^##+\s+ARCHIVE.*?(?=(?:\n##+|\Z))', new_content, re.DOTALL | re.MULTILINE | re.IGNORECASE)
        if archive_match:
            start, end = archive_match.span()
            archived_block = archive_match.group(0).rstrip() + f"\n{archived_entry}\n"
            new_content = new_content[:start] + archived_block + new_content[end:]
        else:
            new_content = f"{new_content.strip()}\n\n## ARCHIVE\n{archived_entry}\n"

        return new_content, task_lines[0]

    @staticmethod
    def delete_task(content: str, line_start: int, line_end: int) -> Tuple[str, Optional[str]]:
        """Removes a task block permanently from the markdown content."""
        lines = content.splitlines()
        if not (0 <= line_start < len(lines) and line_start < line_end <= len(lines)):
            return content, None
        
        deleted_line = lines[line_start]
        del lines[line_start:line_end]
        return "\n".join(lines) + "\n", deleted_line

    @staticmethod
    def generate_dependency_mermaid(tasks: List[Task]) -> str:
        """Generates Mermaid flowchart diagram with sanitized labels to prevent syntax errors."""
        if not tasks:
            return "graph TD\n  Empty[\"No tasks available\"]"

        def _clean_mermaid_str(text: str) -> str:
            # Escape quotes and sanitize delimiters
            s = str(text or "").replace('"', "'").replace('[', '(').replace(']', ')').replace('{', '(').replace('}', ')')
            s = re.sub(r'[\r\n]+', ' ', s).strip()
            return s

        lines = [
            "graph LR",
            "  classDef default fill:#161b22,stroke:#30363d,stroke-width:1px,color:#c9d1d9;",
            "  classDef blockedNode fill:#3d1117,stroke:#f85149,stroke-width:2px,color:#ff7b72;",
            "  classDef depNode fill:#2d1b00,stroke:#d29922,stroke-width:1.5px,color:#e3b341;",
            "  classDef doneNode fill:#102416,stroke:#2ea043,stroke-width:1px,color:#7ee787;"
        ]

        edges = []
        has_relations = False

        for i, t in enumerate(tasks):
            t_id = f"T{i}"
            safe_title = _clean_mermaid_str(t.clean_text)[:35]
            if len(t.clean_text) > 35:
                safe_title += "..."

            status_icon = "✅ " if t.is_done else ("🔴 #p1 " if t.prio == 1 else "")
            node_label = f'{t_id}["{status_icon}{safe_title}"]'
            lines.append(f"  {node_label}")

            if t.is_done:
                lines.append(f"  class {t_id} doneNode")
            elif t.blocked:
                lines.append(f"  class {t_id} blockedNode")

            if t.blocked:
                has_relations = True
                safe_block = _clean_mermaid_str(t.blocked)[:30]
                b_id = f"B{i}"
                lines.append(f'  {b_id}{{"🛑 {safe_block}"}}')
                lines.append(f"  class {b_id} blockedNode")
                edges.append(f"  {t_id} -.->|Blocked by| {b_id}")

            if t.dep:
                has_relations = True
                safe_dep = _clean_mermaid_str(t.dep)[:30]
                d_id = f"D{i}"
                lines.append(f'  {d_id}(["🔗 {safe_dep}"])')
                lines.append(f"  class {d_id} depNode")
                edges.append(f"  {t_id} -->|Depends on| {d_id}")

        if not has_relations:
            lines.append("  Info[\"No explicit #blocked: or #dep: tags in current backlog.\"]")

        return "\n".join(lines + edges)
