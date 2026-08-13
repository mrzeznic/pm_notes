import datetime
from pathlib import Path
from typing import List, Callable, Optional

class AILogger:
    """Manages system, task, and AI event logs for UI streaming and file persistence."""
    logs: List[str] = []
    log_file: Optional[Path] = None
    ui_refresh_callback: Optional[Callable[[], None]] = None

    @classmethod
    def setup(cls, log_file: Path):
        cls.log_file = log_file

    @classmethod
    def log(cls, message: str, log_type: str = "info"):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        icons = {
            "info": "ℹ️",
            "success": "✅",
            "warning": "⚠️",
            "error": "🚨",
            "ai": "🤖"
        }
        icon = icons.get(log_type, "•")

        # 1. Persist to system log file
        if cls.log_file:
            try:
                with open(cls.log_file, "a", encoding="utf-8") as f:
                    f.write(f"[{datetime.datetime.now().isoformat()}] [{log_type.upper()}] {message}\n")
            except Exception:
                pass

        # 2. Add truncated entry to UI logs list (keep last 50 items)
        msg_str = str(message).strip()
        short_msg = msg_str if len(msg_str) <= 80 else msg_str[:77] + "..."
        cls.logs.append(f"[{ts}] {icon} {short_msg}")
        if len(cls.logs) > 50:
            cls.logs.pop(0)

        # 3. Trigger UI update if listener is registered
        if cls.ui_refresh_callback:
            try:
                cls.ui_refresh_callback()
            except Exception:
                pass
