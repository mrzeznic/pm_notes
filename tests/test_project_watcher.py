import asyncio
import pytest
from pathlib import Path
from watchdog.events import FileModifiedEvent
from services.project_watcher import ProjectWatcher, ProjectEventHandler

@pytest.mark.asyncio
async def test_watcher_event_trigger(tmp_path):
    # Setup mock project dir
    project_dir = tmp_path / "TestProject"
    project_dir.mkdir()
    notes_file = project_dir / "notes.md"
    notes_file.touch()

    # Callback tracking
    called = False
    def mock_callback():
        nonlocal called
        called = True

    # Initialize watcher
    watcher = ProjectWatcher(mock_callback)
    watcher.watch(project_dir)

    # Manually fire the watchdog event handler
    event = FileModifiedEvent(str(notes_file))
    watcher.event_handler.on_modified(event)

    # Yield control to the event loop so call_soon_threadsafe can execute
    await asyncio.sleep(0.1)

    assert called is True
    watcher.stop()
