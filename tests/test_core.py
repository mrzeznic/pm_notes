import os
import shutil
import tempfile
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.config import load_config, validate_config, save_config
from core.security import clean_ansi, validate_projects_root, sanitize_model_name
from models.task import Task, Project
from services.markdown_parser import MarkdownParser
from services.project_service import ProjectService
from services.ai_engine import AIEngine

def test_clean_ansi_backspace():
    # Normal string
    assert clean_ansi("hello world") == "hello world"
    # ANSI escape sequences
    assert clean_ansi("\x1b[31mRed Text\x1b[0m") == "Red Text"
    # Stack-based backspace handling without infinite loop
    assert clean_ansi("\x08hello") == "hello"
    assert clean_ansi("abc\x08d") == "abd"
    assert clean_ansi("test\x08\x08\x08\x08reset") == "reset"

def test_validate_projects_root():
    default_root = Path("/tmp/default_projects")
    # Substring 'var' in username should NOT be blocked
    valid_user_path = "/Users/varun/projects"
    res = validate_projects_root(valid_user_path, default_root)
    assert res == Path(valid_user_path).resolve()

    # Restricted system paths should be blocked
    assert validate_projects_root("/etc", default_root) == default_root
    assert validate_projects_root("/System", default_root) == default_root
    assert validate_projects_root("/Users/morton/.ssh/projects", default_root) == default_root

def test_config_validation():
    cfg = validate_config({
        "WIP_LIMIT": "10",
        "MODEL_PREFS": {"Summary": "invalid_value"},
        "PROJECTS_ROOT": "projects"
    })
    assert isinstance(cfg["WIP_LIMIT"], int)
    assert cfg["WIP_LIMIT"] == 10
    assert cfg["MODEL_PREFS"]["Summary"] == "local"

def test_markdown_parser_multiline_summary_and_update():
    sample_notes = """# Project Info
Mission: Test mission
Lead: Jane Doe

## Tasks
- [ ] Task 1 #p1

## PROJECT SUMMARY
Line 1: Project kickoff complete.
Line 2: Core services are operational.
Line 3: Next milestone is scheduled for Q4.

## ARCHIVE
- [x] Initial setup
"""
    # 1. Multi-line extraction
    summary = MarkdownParser.extract_summary(sample_notes)
    assert "Line 1: Project kickoff complete." in summary
    assert "Line 2: Core services are operational." in summary
    assert "Line 3: Next milestone is scheduled for Q4." in summary

    # 2. Non-accumulating update
    updated_1 = MarkdownParser.update_summary(sample_notes, "New summary replacement.")
    assert "New summary replacement." in updated_1
    assert "Line 1: Project kickoff" not in updated_1

    updated_2 = MarkdownParser.update_summary(updated_1, "Final summary text.")
    assert "Final summary text." in updated_2
    assert "New summary replacement." not in updated_2
    assert updated_2.count("## PROJECT SUMMARY") == 1

def test_markdown_parser_multiline_project_info():
    notes = """# Project Info
Mission: Build high performance engine.
Tech Stack: Python, NiceGUI, SQLite.
Lead Engineer: Alex Mercer.

## Tasks
- [ ] Task A
"""
    info = MarkdownParser.extract_project_info(notes)
    assert "Mission: Build high performance engine." in info
    assert "Tech Stack: Python, NiceGUI, SQLite." in info
    assert "Lead Engineer: Alex Mercer." in info

def test_markdown_parser_subsections():
    notes = """# Project
## Tasks
- [ ] Root Task #p1
### Frontend Subsystem
- [ ] UI Component #p2
### Backend API
- [ ] API Endpoint #p3
## Notes
- [ ] Non-task checkbox
"""
    tasks = MarkdownParser.parse_tasks(notes)
    assert len(tasks) == 3
    titles = [t.clean_text for t in tasks]
    assert "Root Task" in titles
    assert "UI Component" in titles
    assert "API Endpoint" in titles

def test_markdown_parser_accurate_stats():
    notes = """## Tasks
- [ ] Open Task 1 #p1 @2026-08-30
- [ ] Open Task 2 #p2 #blocked: DB migration
- [x] Done Task #p1 #blocked: Was blocked earlier
"""
    todos, blockers, urgent, prog = MarkdownParser.calculate_stats(notes)
    assert todos == 1      # Only unblocked open task
    assert blockers == 1   # Done task with #blocked is NOT counted
    assert urgent == 1     # Done task with #p1 is NOT counted
    assert abs(prog - 33.33) < 0.1

def test_markdown_parser_backslash_safety():
    notes = "## Tasks\n- [ ] Initial task\n\n## PROJECT SUMMARY\nInitial\n"
    # Backslash \1 or \alpha should not corrupt content
    res = MarkdownParser.add_task(notes, r"Task with regex \1 and path C:\temp")
    assert r"Task with regex \1 and path C:\temp" in res

    summary_res = MarkdownParser.update_summary(notes, r"Summary with LaTeX \alpha + \beta and \1")
    assert r"Summary with LaTeX \alpha + \beta and \1" in summary_res

def test_task_status_and_deletion():
    notes = "## Tasks\n- [ ] Task A #in_progress\n- [ ] Task B\n"
    tasks = MarkdownParser.parse_tasks(notes)
    assert tasks[0].kanban_status == "in_progress"
    
    # Serialization
    t = tasks[0]
    line = t.to_markdown_line()
    assert "#in_progress" in line

    # Deletion
    updated, deleted = MarkdownParser.delete_task(notes, 1)
    assert deleted == "- [ ] Task A #in_progress"
    assert "Task A" not in updated
    assert "Task B" in updated

def test_mermaid_generation_sanitization():
    tasks = [
        Task(id="1", line_idx=0, clean_text="Task [with brackets] and \"quotes\"", raw_text="", is_done=False, blocked="Blocker (with parens)"),
        Task(id="2", line_idx=1, clean_text="Task 2", raw_text="", is_done=True, dep="Dep {with braces}")
    ]
    mermaid = MarkdownParser.generate_dependency_mermaid(tasks)
    assert "graph LR" in mermaid
    assert "Blocked by" in mermaid
    assert "Depends on" in mermaid
    # Verify braces/brackets were sanitized
    assert "{" not in mermaid.split("graph LR")[1].split("classDef")[0]

def test_project_service_scaffolding_and_crud():
    with tempfile.TemporaryDirectory() as tmp_dir:
        root_path = Path(tmp_dir)
        
        # 1. Create project
        proj = ProjectService.create_new_project(root_path, "Test_Service", mission="Mission X", tech_stack="Go", lead="Jane")
        assert proj.path.exists()
        assert "Mission X" in proj.path.read_text()

        # 2. Scan projects
        active, archived = ProjectService.scan_projects(root_path)
        assert len(active) == 1
        assert active[0].name == "Test_Service"

        # 3. Archive project
        archived_success = ProjectService.archive_project(active[0], root_path)
        assert archived_success
        active_after, archived_after = ProjectService.scan_projects(root_path, show_archived=True)
        assert len(active_after) == 0
        assert len(archived_after) == 1

        # 4. Unarchive project
        restore_success = ProjectService.unarchive_project(archived_after[0], root_path)
        assert restore_success
        active_restored, _ = ProjectService.scan_projects(root_path)
        assert len(active_restored) == 1
        assert "Test_Service" in active_restored[0].name

if __name__ == "__main__":
    test_clean_ansi_backspace()
    test_validate_projects_root()
    test_config_validation()
    test_markdown_parser_multiline_summary_and_update()
    test_markdown_parser_multiline_project_info()
    test_markdown_parser_subsections()
    test_markdown_parser_accurate_stats()
    test_markdown_parser_backslash_safety()
    test_task_status_and_deletion()
    test_mermaid_generation_sanitization()
    test_project_service_scaffolding_and_crud()
    print("All comprehensive unit tests passed successfully!")
