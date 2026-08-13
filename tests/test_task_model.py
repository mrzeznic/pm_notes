from models.task import Task
from pathlib import Path

def test_task_serialization():
    t = Task(
        id="123",
        line_start=0,
        line_end=1,
        clean_text="Test Task",
        raw_text="- [ ] Test Task #p1 @2026-10-31",
        is_done=False,
        prio=1,
        due="2026-10-31",
        status_override="todo",
        project_path=Path("/some/path/notes.md")
    )
    
    md_line = t.to_markdown_line()
    assert "- [ ]" in md_line
    assert "Test Task" in md_line
    assert "#p1" in md_line
    assert "@2026-10-31" in md_line

def test_task_done_serialization():
    t = Task(
        id="123",
        line_start=0,
        line_end=1,
        clean_text="Done Task",
        raw_text="",
        is_done=True,
        status_override="done"
    )
    
    md_line = t.to_markdown_line()
    assert "- [x]" in md_line
    assert "Done Task" in md_line

def test_task_body_serialization():
    t = Task(
        id="123",
        line_start=0,
        line_end=2,
        clean_text="Parent Task",
        raw_text="",
        is_done=False,
        status_override="todo",
        body_lines=["  - Sub item", "  Some desc"]
    )
    
    md = t.to_markdown_line()
    lines = md.splitlines()
    assert len(lines) == 3
    assert lines[0].strip() == "- [ ] Parent Task"
    assert lines[1] == "  - Sub item"
    assert lines[2] == "  Some desc"
