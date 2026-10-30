"""
Configuration Loader
Loads and validates rules.yaml and prompts.yaml configurations.
"""

import os
import yaml
from pathlib import Path
from typing import Dict, Any

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = BASE_DIR / "config"

_rules_cache = None
_prompts_cache = None

def get_rules_path() -> Path:
    env_path = os.getenv("RULES_PATH")
    if env_path:
        return Path(env_path)
    return CONFIG_DIR / "rules.yaml"

def get_prompts_path() -> Path:
    env_path = os.getenv("PROMPTS_PATH")
    if env_path:
        return Path(env_path)
    return CONFIG_DIR / "prompts.yaml"

def load_rules(force_reload: bool = False) -> Dict[str, Any]:
    global _rules_cache
    if _rules_cache is None or force_reload:
        path = get_rules_path()
        if not path.exists():
            raise FileNotFoundError(f"Rules configuration file not found at {path}")
        with open(path, "r", encoding="utf-8") as f:
            _rules_cache = yaml.safe_load(f)
    return _rules_cache

def load_prompts(force_reload: bool = False) -> Dict[str, Any]:
    global _prompts_cache
    if _prompts_cache is None or force_reload:
        path = get_prompts_path()
        if not path.exists():
            raise FileNotFoundError(f"Prompts configuration file not found at {path}")
        with open(path, "r", encoding="utf-8") as f:
            _prompts_cache = yaml.safe_load(f)
    return _prompts_cache
