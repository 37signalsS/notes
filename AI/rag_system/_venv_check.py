import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_VENV_PYTHON = os.path.join(_SCRIPT_DIR, "venv", "bin", "python3")


def ensure_venv() -> None:
    if sys.executable != _VENV_PYTHON and os.path.exists(_VENV_PYTHON) and not os.environ.get("RAG_VENV_EXEC"):
        os.environ["RAG_VENV_EXEC"] = "1"
        try:
            os.execve(_VENV_PYTHON, [_VENV_PYTHON] + sys.argv, os.environ)
        except OSError as e:
            print(f"Warning: Failed to re-exec into venv ({e}), continuing with current interpreter", file=sys.stderr)
