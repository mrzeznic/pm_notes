import datetime
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List

@dataclass
class Task:
    id: str
    line_idx: int
    clean_text: str
    raw_text: str
    is_done: bool
    prio: int = 4  # 1: High, 2: Medium, 3: Low, 4: None
    blocked: Optional[str] = None
    dep: Optional[str] = None
    desc: str = ""
    due: Optional[str] = None
    overdue: bool = False
    is_archived: bool = False
    section: Optional[str] = None
    status_override: Optional[str] = None  # Explicit status: 'todo', 'in_progress', 'blocked', 'done'

    @classmethod
    def generate_id(cls, raw_line: str, line_idx: int) -> str:
        return hashlib.md5(f"{line_idx}:{raw_line.strip()}".encode('utf-8')).hexdigest()[:10]

    @property
    def kanban_status(self) -> str:
        """Determines task column in Kanban view: 'done', 'blocked', 'in_progress', or 'todo'."""
        if self.status_override in {"todo", "in_progress", "blocked", "done"}:
            return self.status_override
        if self.is_done:
            return "done"
        if self.blocked and self.blocked.strip():
            return "blocked"
        if "#in_progress" in self.raw_text.lower() or "#wip" in self.raw_text.lower():
            return "in_progress"
        return "todo"

    def to_markdown_line(self) -> str:
        """Converts task back into standard markdown task format."""
        status_val = self.kanban_status
        is_done = (status_val == "done") or self.is_done
        status_box = "x" if is_done else " "
        line = f"- [{status_box}] {self.clean_text}"
        
        if self.prio in {1, 2, 3}:
            line += f" #p{self.prio}"
            
        if status_val == "in_progress" and not is_done:
            line += " #in_progress"
            
        if self.due:
            line += f" @{self.due}"
            
        if status_val == "blocked":
            block_reason = self.blocked.strip() if self.blocked else "Unknown"
            line += f" #blocked: {block_reason}"
            
        if self.dep and self.dep.strip():
            line += f" #dep: {self.dep.strip()}"
            
        if self.desc and self.desc.strip():
            line += f" ({self.desc.strip()})"
            
        return line

@dataclass
class Project:
    name: str
    dir: Optional[Path] = None
    path: Optional[Path] = None
    todos: int = 0
    in_progress: int = 0
    blockers: int = 0
    urgent: int = 0
    progress: float = 0.0
    is_archived: bool = False
