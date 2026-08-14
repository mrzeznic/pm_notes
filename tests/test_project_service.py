import pytest
from pathlib import Path
from services.project_service import ProjectService
from models.task import Project

def test_atomic_write(tmp_path):
    test_file = tmp_path / "test.md"
    ProjectService.atomic_write(test_file, "Hello World")
    
    assert test_file.exists()
    assert test_file.read_text(encoding='utf-8') == "Hello World"
    
    # Overwrite
    ProjectService.atomic_write(test_file, "Updated")
    assert test_file.read_text(encoding='utf-8') == "Updated"

def test_create_backup(tmp_path):
    test_file = tmp_path / "notes.md"
    test_file.write_text("Test content")
    
    ProjectService.create_backup(test_file)
    
    backups = list(tmp_path.glob(".notes.md.bak_*"))
    assert len(backups) == 1
    assert backups[0].read_text() == "Test content"

def test_archive_project(tmp_path):
    # Setup project
    root_path = tmp_path
    proj_dir = root_path / "MyProject"
    proj_dir.mkdir()
    notes = proj_dir / "notes.md"
    notes.write_text("Some tasks")
    
    p = Project(name="MyProject", dir=proj_dir, path=notes, is_archived=False)
    
    result = ProjectService.archive_project(p, root_path)
    assert result is True
    
    import datetime
    current_year = datetime.date.today().year
    archive_dir = root_path / f"_Archive_{current_year}" / "MyProject"
    assert archive_dir.exists()
    assert (archive_dir / "notes.md").exists()
    assert not proj_dir.exists()

def test_scan_projects_discovery(tmp_path):
    root = tmp_path / "projects"
    root.mkdir()
    
    # Valid active project
    proj_a = root / "ProjA"
    proj_a.mkdir()
    (proj_a / "notes.md").write_text("- [ ] Task 1\n- [ ] Task 2\n")
    
    # Project missing notes (should auto-create)
    proj_b = root / "ProjB"
    proj_b.mkdir()
    
    # Hidden folder (should be ignored)
    proj_hidden = root / ".Hidden"
    proj_hidden.mkdir()
    
    active, archived = ProjectService.scan_projects(root, show_archived=False)
    
    assert len(active) == 2
    assert len(archived) == 0
    
    names = [p.name for p in active]
    assert "ProjA" in names
    assert "ProjB" in names
    assert ".Hidden" not in names
    
    # Check stats for ProjA
    pa = next(p for p in active if p.name == "ProjA")
    assert pa.todos == 2
    assert pa.progress == 0.0
    
    # Check that notes.md was created for ProjB
    pb = next(p for p in active if p.name == "ProjB")
    assert pb.path.exists()

def test_scan_projects_archived(tmp_path):
    root = tmp_path / "projects"
    root.mkdir()
    
    # Active project
    proj_a = root / "ProjA"
    proj_a.mkdir()
    
    # Archived project
    archive_dir = root / "_Archive_2026" / "ProjOld"
    archive_dir.mkdir(parents=True)
    (archive_dir / "notes.md").write_text("- [x] Done Task")
    
    # Scan with show_archived=True
    active, archived = ProjectService.scan_projects(root, show_archived=True)
    
    assert len(active) == 1
    assert len(archived) == 1
    assert archived[0].name == "ProjOld"
    assert archived[0].is_archived is True
