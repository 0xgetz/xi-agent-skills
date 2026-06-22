"""Auto-detect and log skill script executions and imports. Loaded by Python at startup."""
import atexit
import json
import os
import sys
import time

_SKILLS_DIR = "/home/user/skills/"
_TOOLS_DIR = "/home/user/skills/.tools/"
_LOG_PATH = "/home/user/.skill_usage.jsonl"  # hidden so workspace persistence skips it (matches '! -path */.*')


def _log_entry(entry):
    try:
        with open(_LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def _extract_skill(path):
    if _SKILLS_DIR not in path or _TOOLS_DIR in path:
        return None
    rest = path[path.index(_SKILLS_DIR) + len(_SKILLS_DIR):]
    name = rest.split("/", 1)[0]
    return name if name and not name.startswith(".") else None


def _auto_track():
    script = os.path.abspath(sys.argv[0]) if sys.argv else ""
    skill_name = _extract_skill(script)
    if not skill_name:
        return

    start = time.time()
    exc_info = {"error": None}
    original_excepthook = sys.excepthook

    def _on_exception(exc_type, exc_value, exc_tb):
        exc_info["error"] = f"{exc_type.__name__}: {exc_value}"
        original_excepthook(exc_type, exc_value, exc_tb)

    sys.excepthook = _on_exception

    def _on_exit():
        entry = {
            "ts": time.time(),
            "skill": skill_name,
            "script": script,
            "event": "execute",
            "duration_ms": round((time.time() - start) * 1000, 2),
        }
        if exc_info["error"]:
            entry["error"] = exc_info["error"]
        _log_entry(entry)

    atexit.register(_on_exit)


def _track_skill_imports():
    """Track when skill modules are imported at runtime via audit hook.

    sys.addaudithook cannot be removed — the agent cannot disable this.
    """
    logged_imports = set()

    def _audit_hook(event, args):
        if event != "import":
            return
        try:
            module_name = args[0] if args else None
            if not module_name:
                return
            # PEP 578: args = (name, filename, sys.path, sys.path_hooks, sys.meta_path)
            filepath = args[1] if len(args) > 1 and args[1] else ""
            if not filepath:
                return
            skill_name = _extract_skill(filepath)
            if not skill_name:
                return
            cache_key = (skill_name, filepath)
            if cache_key in logged_imports:
                return
            logged_imports.add(cache_key)
            _log_entry({
                "ts": time.time(),
                "skill": skill_name,
                "script": filepath,
                "event": "import",
            })
        except Exception:
            pass

    try:
        sys.addaudithook(_audit_hook)
    except Exception:
        pass


_auto_track()
_track_skill_imports()
