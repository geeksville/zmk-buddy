"""Preflight check for PySide6 availability.

This module provides a function to check if PySide6 is properly installed
before attempting to import it in the main application.
"""


def has_pyqt6() -> bool:
    """Probe whether PySide6 is installed (both python code and required native dependencies)."""
    try:
        # 1. This triggers the dynamic linker to load the C++ shared libraries.
        #    If system deps are missing, this explodes.
        # pylint: disable=unused-import
        from PySide6 import (
            QtWidgets,
            QtCore,
        )  # pyright: ignore[reportUnusedImport]  # noqa: F401

        return True

    except Exception:
        return False
