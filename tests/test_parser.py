import pytest
from services.markdown_parser import MarkdownParser
from models.task import Task
from pathlib import Path

def test_parse_simple_tasks():
    content = """# Title
- [ ] Task 1
- [x] Task 2
"""
    test_path = Path("/tmp/notes.md")
    tasks = MarkdownParser.parse_tasks(content, project_path=test_path)
    assert len(tasks) == 2
    assert tasks[0].clean_text == "Task 1"
    assert not tasks[0].is_done
    assert tasks[0].project_path == test_path
    assert tasks[1].clean_text == "Task 2"
    assert tasks[1].is_done

def test_parse_multiline_task():
    content = """# Title
- [ ] Multi-line task
  This is line 2.
  This is line 3.
  - Sub point
"""
    tasks = MarkdownParser.parse_tasks(content)
    assert len(tasks) == 1
    t = tasks[0]
    assert t.clean_text == "Multi-line task"
    assert len(t.body_lines) == 3
    assert t.body_lines[0].strip() == "This is line 2."
    assert t.body_lines[-1].strip() == "- Sub point"

def test_add_task():
    content = "# Title\n- [ ] Task 1\n"
    updated = MarkdownParser.add_task(content, "Task 2")
    assert "- [ ] Task 2" in updated
    assert "- [ ] Task 1" in updated

def test_delete_task():
    content = """# Title
- [ ] Task 1
  Body 1
- [ ] Task 2
  Body 2
"""
    tasks = MarkdownParser.parse_tasks(content)
    assert len(tasks) == 2
    
    t1 = tasks[0]
    updated, deleted_line = MarkdownParser.delete_task(content, t1.line_start, t1.line_end)
    assert "Task 1" in deleted_line
    assert "Task 2" in updated
    assert "Task 1" not in updated
    assert "Body 1" not in updated

def test_archive_task():
    content = """# Title
## Tasks
- [ ] Task 1

## ARCHIVE
"""
    tasks = MarkdownParser.parse_tasks(content)
    t1 = tasks[0]
    
    updated, archived_line = MarkdownParser.archive_task(content, t1.line_start, t1.line_end)
    assert "Task 1" in archived_line
    
    # Should move it under ARCHIVE
    assert "## ARCHIVE" in updated
    archive_section = updated.split("## ARCHIVE")[1]
    assert "- [ ] Task 1" in archive_section
    assert "(Archived:" in archive_section

def test_insert_subtasks():
    content = """# Title
- [ ] Parent task
- [ ] Other task
"""
    tasks = MarkdownParser.parse_tasks(content)
    parent = tasks[0]
    
    subtasks = ["Sub 1", "- [ ] Sub 2"]
    updated = MarkdownParser.insert_subtasks(content, parent.line_end, subtasks)
    
    lines = updated.splitlines()
    # Check that they were inserted right after the parent task
    assert lines[1] == "- [ ] Parent task"
    assert lines[2] == "- [ ] Sub 1"
    assert lines[3] == "- [ ] Sub 2"
    assert lines[4] == "- [ ] Other task"

def test_generate_dependency_mermaid():
    tasks = [
        Task(
            id="T0", line_start=1, line_end=1,
            clean_text='Implement "Login" UI',
            raw_text='- [ ] Implement "Login" UI #blocked: Design pending',
            is_done=False,
            blocked="Design pending"
        ),
        Task(
            id="T1", line_start=2, line_end=2,
            clean_text="Setup Auth Service",
            raw_text="- [ ] Setup Auth Service #dep: T0",
            is_done=False,
            dep="T0"
        ),
        Task(
            id="T2", line_start=3, line_end=3,
            clean_text="Database Migration",
            raw_text="- [x] Database Migration",
            is_done=True
        )
    ]
    
    mermaid_str = MarkdownParser.generate_dependency_mermaid(tasks)
    
    # Check diagram type
    assert "graph LR" in mermaid_str
    
    # Check node sanitization and creation
    assert 'T0["Implement \'Login\' UI"]' in mermaid_str  # quotes should be escaped to single quotes
    
    # Check classes
    assert 'class T0 blockedNode' in mermaid_str
    assert 'class T2 doneNode' in mermaid_str
    
    # Check edges
    assert 'T0 -.->|Blocked by| B0' in mermaid_str
    assert 'B0{"🛑 Design pending"}' in mermaid_str
    
    assert 'T1 -->|Depends on| D1' in mermaid_str
    assert 'D1(["🔗 T0"])' in mermaid_str
    assert 'class D1 depNode' in mermaid_str
