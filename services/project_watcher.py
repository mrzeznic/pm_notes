import asyncio
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from typing import Callable, Dict, Set
from core.logger import AILogger

# Global observer shared across all sessions
_global_observer = None
_watched_paths: Dict[str, Set[Callable]] = {}

class ProjectEventHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if event.is_directory or not event.src_path.endswith('notes.md'):
            return
        
        parent_dir = str(Path(event.src_path).parent)
        if parent_dir in _watched_paths:
            callbacks = _watched_paths[parent_dir]
            for callback in list(callbacks):
                try:
                    loop = asyncio.get_event_loop()
                    if not loop.is_closed():
                        loop.call_soon_threadsafe(callback)
                except Exception:
                    pass

class ProjectWatcher:
    def __init__(self, on_change_callback: Callable):
        global _global_observer
        if _global_observer is None:
            _global_observer = Observer()
            _global_observer.start()
            
        self.callback = on_change_callback
        self.current_path = None
        self.event_handler = ProjectEventHandler()

    def watch(self, path: Path):
        global _global_observer, _watched_paths
        
        if self.current_path == path:
            return
            
        self.stop()
        
        if not path or not path.exists() or not path.is_dir():
            return

        self.current_path = path
        path_str = str(path)
        
        if path_str not in _watched_paths:
            _watched_paths[path_str] = set()
            try:
                _global_observer.schedule(self.event_handler, path_str, recursive=False)
                AILogger.log(f"Started watching directory: {path}", "info")
            except Exception as e:
                AILogger.log(f"Watchdog scheduling error for {path}: {e}", "warning")
                
        _watched_paths[path_str].add(self.callback)

    def stop(self):
        global _watched_paths
        if self.current_path:
            path_str = str(self.current_path)
            if path_str in _watched_paths and self.callback in _watched_paths[path_str]:
                _watched_paths[path_str].remove(self.callback)
                
            self.current_path = None
