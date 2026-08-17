import json
import os
import sys
from pathlib import Path
from typing import Dict, Any

from .security import validate_projects_root, sanitize_model_name

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_PROJECTS_DIR = BASE_DIR / "projects"
SYSTEM_LOG_FILE = BASE_DIR / "tpm_system.log"
CONFIG_FILE = BASE_DIR / "tpm_config.json"
DEFAULTS_FILE = BASE_DIR / "tpm_defaults.json"

DEFAULT_CONFIG: Dict[str, Any] = {
    "PROJECTS_ROOT": str(DEFAULT_PROJECTS_DIR),
    "LOCAL_MODEL": "qwen2.5:7b",
    "OLLAMA_BASE_URL": "http://localhost:11434",
    "CLOUD_MODEL": "gpt-4o",
    "GITHUB_MODELS_BASE_URL": "https://models.inference.ai.azure.com",
    "GITHUB_TOKEN": os.environ.get("GITHUB_TOKEN", ""),
    "GLOBAL_MODEL_CMD": "gh copilot chat -p",
    "WIP_LIMIT": 5,
    "MODEL_PREFS": {
        "Summary": "local",
        "Chat": "cloud",
        "Daily Roadmap": "cloud",
        "Refactor Task": "cloud",
        "Refactor Notes": "cloud",
        "Executive": "cloud",
        "Tech Plan": "cloud",
        "Triage": "cloud",
        "Groom": "cloud"
    }
}

def validate_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Ensures configuration paths and model values are secure and sane."""
    # Validate Projects Root (resolve relative paths against BASE_DIR)
    raw_root = str(config.get("PROJECTS_ROOT", DEFAULT_PROJECTS_DIR)).strip()
    if not raw_root or raw_root == "projects":
        raw_root = str(DEFAULT_PROJECTS_DIR)
    elif not os.path.isabs(raw_root):
        raw_root = str((BASE_DIR / raw_root).resolve())

    validated_root = validate_projects_root(raw_root, DEFAULT_PROJECTS_DIR)
    config["PROJECTS_ROOT"] = str(validated_root)

    # Sanitize Model Names
    config["LOCAL_MODEL"] = sanitize_model_name(config.get("LOCAL_MODEL", "qwen2.5:7b"), "qwen2.5:7b")
    config["CLOUD_MODEL"] = sanitize_model_name(config.get("CLOUD_MODEL", "gpt-4o"), "gpt-4o")
    config["GLOBAL_MODEL_CMD"] = sanitize_model_name(config.get("GLOBAL_MODEL_CMD", "gh copilot chat -p"), "gh copilot chat -p")
    config["OLLAMA_BASE_URL"] = str(config.get("OLLAMA_BASE_URL", "http://localhost:11434")).strip()
    config["GITHUB_MODELS_BASE_URL"] = str(config.get("GITHUB_MODELS_BASE_URL", "https://models.inference.ai.azure.com")).strip()
    
    # Token - if empty in config, check environment variable
    token = str(config.get("GITHUB_TOKEN", "")).strip()
    if not token and os.environ.get("GITHUB_TOKEN"):
        token = os.environ.get("GITHUB_TOKEN", "").strip()
    config["GITHUB_TOKEN"] = token

    # WIP limit (strictly integer >= 1)
    try:
        config["WIP_LIMIT"] = max(1, int(config.get("WIP_LIMIT", 5)))
    except (ValueError, TypeError):
        config["WIP_LIMIT"] = 5

    # Model preferences
    if "MODEL_PREFS" not in config or not isinstance(config["MODEL_PREFS"], dict):
        config["MODEL_PREFS"] = DEFAULT_CONFIG["MODEL_PREFS"].copy()
    else:
        new_prefs = {}
        for tool, default_val in DEFAULT_CONFIG["MODEL_PREFS"].items():
            val = config["MODEL_PREFS"].get(tool, default_val)
            if val not in {"local", "cloud"}:
                val = default_val
            new_prefs[tool] = val
        config["MODEL_PREFS"] = new_prefs

    return config

def load_config() -> Dict[str, Any]:
    """Loads configuration with hierarchy: user config > external defaults > hardcoded defaults."""
    merged = DEFAULT_CONFIG.copy()

    # 1. Load external defaults if available
    if DEFAULTS_FILE.exists():
        try:
            with open(DEFAULTS_FILE, "r", encoding="utf-8") as f:
                loaded_defaults = json.load(f)
                if loaded_defaults.get("PROJECTS_ROOT") == "projects":
                    loaded_defaults["PROJECTS_ROOT"] = str(DEFAULT_PROJECTS_DIR)
                merged.update(loaded_defaults)
        except Exception as e:
            print(f"Error loading defaults: {e}", file=sys.stderr)

    # 2. Merge user config
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
                if "MODEL_PREFS" in user_cfg and "MODEL_PREFS" in merged:
                    merged["MODEL_PREFS"].update(user_cfg["MODEL_PREFS"])
                    del user_cfg["MODEL_PREFS"]
                merged.update(user_cfg)
        except Exception as e:
            print(f"Error loading user config: {e}", file=sys.stderr)

    return validate_config(merged)

def save_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Validates and saves the configuration to JSON."""
    validated = validate_config(config)
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(validated, f, indent=4)
    except Exception as e:
        print(f"Error saving config: {e}", file=sys.stderr)
    return validated
