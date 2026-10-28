"""Ephemeral runtime artifacts; no fixed paths or local credential discovery."""
from pathlib import Path
import tempfile


def artifact_root(test_class) -> Path:
    directory = tempfile.TemporaryDirectory(prefix="bridge-runtime-")
    test_class.addClassCleanup(directory.cleanup)
    return Path(directory.name)
