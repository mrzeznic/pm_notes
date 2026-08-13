import re
import sys
from pathlib import Path

# Absolute system paths that should never be used as a projects workspace root
RESTRICTED_SYSTEM_DIRS = [
    Path(p).resolve() for p in [
        "/etc", "/private/etc",
        "/var", "/private/var",
        "/root",
        "/System",
        "/bin", "/sbin",
        "/usr", "/usr/bin", "/usr/sbin"
    ]
]
RESTRICTED_FOLDER_NAMES = {".ssh", ".gnupg", ".aws"}

def validate_projects_root(root_str: str, default_root: Path) -> Path:
    """Ensures projects directory doesn't traverse into restricted OS folders."""
    try:
        path = Path(root_str).expanduser().resolve()
        
        # Check if path is root itself or directly a restricted system directory
        if path == Path("/") or any(path == r or path.is_relative_to(r) for r in RESTRICTED_SYSTEM_DIRS):
            print(f"Security Warning: Blocked restricted Projects Root path: {path}", file=sys.stderr)
            return default_root

        # Check if any path component is a restricted sensitive folder
        if any(part in RESTRICTED_FOLDER_NAMES for part in path.parts):
            print(f"Security Warning: Blocked sensitive folder in Projects Root: {path}", file=sys.stderr)
            return default_root

        return path
    except Exception:
        return default_root

def clean_ansi(text: str) -> str:
    """Removes ANSI escape codes and processes terminal backspaces safely using a stack."""
    if not text:
        return ""
    # Strip ANSI escape sequences
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    text = ansi_escape.sub('', text)

    # Process backspaces via character stack to prevent infinite loops
    stack = []
    for char in text:
        if char == '\x08':
            if stack:
                stack.pop()
        else:
            stack.append(char)
    cleaned = "".join(stack)

    # Keep newlines, tabs, and printable characters
    return "".join(ch for ch in cleaned if ch in {'\n', '\t'} or ord(ch) >= 32).strip()

def sanitize_model_name(val: str, default: str = "qwen2.5:7b") -> str:
    """Sanitizes model name to prevent command/argument injection characters."""
    val_str = str(val).strip()
    if not val_str:
        return default
    if any(char in val_str for char in [";", "&", "|", ">", "<", "$", "`", "\n", "\r"]):
        print(f"Security Warning: Sanitized suspicious characters in model name: {val}", file=sys.stderr)
        return default
    return val_str
