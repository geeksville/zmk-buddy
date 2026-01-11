"""Preflight check for PyGObject/GTK availability.

This module provides a function to check if PyGObject and GTK are properly installed
before attempting to import them in the main application.
"""


def has_gtk() -> bool:
    """Probe whether PyGObject and GTK4 are installed (both python bindings and native libraries)."""
    try:
        # 1. This triggers the dynamic linker to load the shared libraries.
        #    If system deps are missing, this explodes.
        # pylint: disable=unused-import
        import gi  # noqa: F401

        gi.require_version("Gtk", "4.0")
        gi.require_version("WebKit", "6.0")
        from gi.repository import Gtk, WebKit  # pyright: ignore[reportUnusedImport]  # noqa: F401

        return True

    except Exception:
        return False


# Keep old name for backward compatibility during transition
def has_pyqt6() -> bool:
    """Deprecated: Use has_gtk() instead. Returns True if GTK is available."""
    return has_gtk()
