"""
Base class for keyboard monitoring implementations.

This module defines the abstract interface that all keyboard monitors must implement.
Uses GObject for signal-based communication.
"""

# pylint: disable=wrong-import-position

import logging
from typing import Callable

import gi

gi.require_version("GObject", "2.0")
from gi.repository import GObject, GLib  # noqa: E402

logger = logging.getLogger(__name__)

# Type alias for keyboard event callbacks
KeyCallback = Callable[[str], None]


class KeyboardMonitorBase(GObject.Object):
    """Base class for keyboard monitoring implementations.

    Subclasses should implement platform-specific keyboard event capture
    (e.g., evdev on Linux, pynput on Windows/macOS).
    """

    __gsignals__ = {
        "key-pressed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "key-released": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def start(self) -> bool:
        """
        Start monitoring keyboard events.

        Returns:
            True if monitoring started successfully, False otherwise
        """
        raise NotImplementedError("Subclasses must implement start()")

    def stop(self) -> None:
        """Stop monitoring keyboard events and clean up resources."""
        raise NotImplementedError("Subclasses must implement stop()")

    def emit_key_pressed(self, key: str) -> None:
        """Emit a key-pressed signal (thread-safe via GLib.idle_add)."""
        GLib.idle_add(self.emit, "key-pressed", key)

    def emit_key_released(self, key: str) -> None:
        """Emit a key-released signal (thread-safe via GLib.idle_add)."""
        GLib.idle_add(self.emit, "key-released", key)
