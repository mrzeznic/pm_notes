import datetime
import hashlib
import os
import shutil
from pathlib import Path
from typing import List, Tuple, Optional

from core.logger import AILogger
from models.task import Project
from services.markdown_parser import MarkdownParser

class ProjectService:
    @staticmethod
    def get_archive_dir(root: Path) -> Path:
        """Returns the dynamic archive path for the current year."""
        current_year = datetime.date.today().year
        archive_path = root / f"_Archive_{current_year}"
        archive_path.mkdir(parents=True, exist_ok=True)
        return archive_path

    @staticmethod
    def atomic_write(path: Path, content: str):
        """Atomically writes content to file using a temporary swap file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_file = path.with_name(f".{path.name}.tmp")
        temp_file.write_text(content, encoding='utf-8')
        temp_file.replace(path)

    @classmethod
    def create_backup(cls, path: Path) -> Optional[Path]:
        """Creates a timestamped backup before destructive actions."""
        if not path or not path.exists():
            return None
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = path.parent / f".{path.name}.bak_{ts}"
        try:
            shutil.copy2(path, backup_path)
            AILogger.log(f"Created backup: {backup_path.name}", "info")
            return backup_path
        except Exception as e:
            AILogger.log(f"Backup failed: {str(e)}", "warning")
            return None

    @staticmethod
    def get_content_hash(path: Optional[Path]) -> str:
        """Generates MD5 content hash for caching AI responses."""
        if not path or not path.exists():
            return ""
        try:
            return hashlib.md5(path.read_bytes()).hexdigest()
        except Exception:
            return ""

    @classmethod
    def ensure_project_notes(cls, project_dir: Path, name: str, mission: str = "", tech_stack: str = "", lead: str = "") -> Path:
        """Ensures a notes.md file exists in the project directory, scaffolding one if missing."""
        project_dir.mkdir(parents=True, exist_ok=True)
        notes_path = project_dir / "notes.md"
        if not notes_path.exists():
            template = (
                f"# Project Info\n"
                f"Mission: {mission or f'Drive forward {name} initiatives.'}\n"
                f"Tech Stack: {tech_stack or 'Python, TypeScript, Cloud Native'}\n"
                f"Lead Engineer: {lead or 'Engineering Lead'}\n\n"
                f"## Tasks\n"
                f"- [ ] Initial architecture review #p1 @{datetime.date.today().strftime('%Y-%m-%d')}\n"
                f"- [ ] Setup repository and CI/CD pipelines #p2\n\n"
                f"## PROJECT SUMMARY\n"
                f"Project {name} has been initialized with core milestones established.\n\n"
                f"## ARCHIVE\n"
            )
            cls.atomic_write(notes_path, template)
            AILogger.log(f"Scaffolded default notes.md for '{name}'", "info")
        return notes_path

    @classmethod
    def create_new_project(cls, root_path: Path, name: str, mission: str = "", tech_stack: str = "", lead: str = "") -> Project:
        """Creates a new project directory and notes.md in the root portfolio."""
        safe_name = "".join(c if c.isalnum() or c in {'_', '-'} else '_' for c in name.strip())
        if not safe_name:
            safe_name = "New_Project"
        
        proj_dir = root_path / safe_name
        if proj_dir.exists():
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            proj_dir = root_path / f"{safe_name}_{ts}"
            safe_name = proj_dir.name

        notes_path = cls.ensure_project_notes(proj_dir, safe_name, mission, tech_stack, lead)
        content = notes_path.read_text(encoding='utf-8', errors='ignore')
        todos, in_progress, blockers, urgent, prog = MarkdownParser.calculate_stats(content)

        AILogger.log(f"Created new project '{safe_name}'", "success")
        return Project(
            name=safe_name,
            dir=proj_dir,
            path=notes_path,
            todos=todos,
            in_progress=in_progress,
            blockers=blockers,
            urgent=urgent,
            progress=prog,
            is_archived=False
        )

    @classmethod
    def scan_projects(cls, root_path: Path, show_archived: bool = False) -> Tuple[List[Project], List[Project]]:
        """Scans active and archived project folders in the portfolio root."""
        root_path.mkdir(parents=True, exist_ok=True)
        active_projects: List[Project] = []
        archived_projects: List[Project] = []

        def scan_dir(path: Path, is_archived: bool) -> List[Project]:
            projs: List[Project] = []
            if not path.exists():
                return projs

            dirs = sorted([d for d in path.iterdir() if d.is_dir() and not d.name.startswith(('.', '_'))])
            for d in dirs:
                notes_path = d / "notes.md"
                if not notes_path.exists() and not is_archived:
                    notes_path = cls.ensure_project_notes(d, d.name)

                todos, in_progress, blockers, urgent, prog = 0, 0, 0, 0, 0.0
                if notes_path.exists():
                    try:
                        content = notes_path.read_text(encoding='utf-8', errors='ignore')
                        todos, in_progress, blockers, urgent, prog = MarkdownParser.calculate_stats(content)
                    except Exception:
                        pass

                projs.append(Project(
                    name=d.name,
                    dir=d,
                    path=notes_path,
                    todos=todos,
                    in_progress=in_progress,
                    blockers=blockers,
                    urgent=urgent,
                    progress=prog,
                    is_archived=is_archived
                ))
            return projs

        active_projects = scan_dir(root_path, is_archived=False)
        archive_dir = cls.get_archive_dir(root_path)

        if show_archived:
            archived_projects = scan_dir(archive_dir, is_archived=True)

        if not active_projects and not archived_projects:
            active_projects = [Project(name="Empty_Portfolio", is_archived=False)]

        return active_projects, archived_projects

    @classmethod
    def archive_project(cls, project: Project, root_path: Path) -> bool:
        """Moves a project directory into the year-based archive."""
        if not project.dir or not project.dir.exists() or project.is_archived:
            return False

        archive_root = cls.get_archive_dir(root_path)
        target_dir = archive_root / project.name

        if target_dir.exists():
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            target_dir = archive_root / f"{project.name}_{ts}"

        try:
            shutil.move(str(project.dir), str(target_dir))
            AILogger.log(f"Archived project '{project.name}' to {archive_root.name}", "success")
            return True
        except Exception as e:
            AILogger.log(f"Failed to archive '{project.name}': {str(e)}", "error")
            return False

    @classmethod
    def unarchive_project(cls, project: Project, root_path: Path) -> bool:
        """Restores an archived project back to the active projects root."""
        if not project.dir or not project.dir.exists() or not project.is_archived:
            return False

        target_dir = root_path / project.name
        if target_dir.exists():
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            target_dir = root_path / f"{project.name}_restored_{ts}"

        try:
            shutil.move(str(project.dir), str(target_dir))
            AILogger.log(f"Restored project '{project.name}' to active portfolio", "success")
            return True
        except Exception as e:
            AILogger.log(f"Failed to restore '{project.name}': {str(e)}", "error")
            return False
