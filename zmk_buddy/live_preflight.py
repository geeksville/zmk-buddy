



def has_pyqt6() -> bool:
    """Probe whether PySide6 is installed (both python code and required native dependencies)."""
    try:
        # 1. This triggers the dynamic linker to load the C++ shared libraries.
        #    If system deps are missing, this explodes.
        from PySide6 import QtWidgets, QtCore   # pyright: ignore[reportUnusedImport]  # noqa: F401
        
        return True
        
    except Exception:
        return False