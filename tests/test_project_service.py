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
