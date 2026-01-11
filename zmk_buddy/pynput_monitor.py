"""
Pynput-based keyboard monitoring for cross-platform support.

This module provides global keyboard monitoring using the pynput library,
which works on Windows, macOS, and Linux (as a fallback when evdev is unavailable).
"""

import logging
from typing import override

from zmk_buddy.keyboard_monitor_base import KeyboardMonitorBase

logger = logging.getLogger(__name__)

# Try to import pynput for cross-platform keyboard monitoring
pynput_available = False
try:
    from pynput import keyboard as pynput_keyboard

    pynput_available = True
except ImportError:
    pass

# Map pynput special keys to SVG labels (for Windows/macOS)
# These are pynput.keyboard.Key enum values
PYNPUT_KEY_MAP: dict[str, str] = {
    "shift": "Shift",
    "shift_l": "Shift",
    "shift_r": "Shift",
    "ctrl": "Control",
    "ctrl_l": "Control",
    "ctrl_r": "Control",
    "alt": "Alt",
    "alt_l": "Alt",
    "alt_r": "AltGr",
    "alt_gr": "AltGr",
    "cmd": "Meta",
    "cmd_l": "Meta",
    "cmd_r": "Meta",
    "caps_lock": "Caps",
    "tab": "Tab",
    "enter": "Enter",
    "return": "Enter",
    "space": "Space",
    "backspace": "Bckspc",
    "delete": "Delete",
    "esc": "Esc",
}


class PynputKeyboardMonitor(KeyboardMonitorBase):
    """Monitor keyboard events using pynput (cross-platform).

    This provides global keyboard monitoring on Windows, macOS,
    and Linux (when evdev is not available).
    """

    def __init__(self) -> None:
        super().__init__()
        self.stop_flag: bool = False
        self._pynput_listener: "pynput_keyboard.Listener | None" = None

    def _pynput_key_to_char(self, key) -> str | None:
        """Convert a pynput key to a character string for SVG lookup"""
        try:
            # Check if it's a regular character key
            if hasattr(key, "char") and key.char:
                return key.char

            # It's a special key - get its name
            if hasattr(key, "name"):
                key_name = key.name.lower()
                return PYNPUT_KEY_MAP.get(key_name, key_name)

            # Try to get the key value as a string
            key_str = str(key).replace("Key.", "").lower()
            return PYNPUT_KEY_MAP.get(key_str, key_str)
        except Exception:
            return None

    @override
    def start(self) -> bool:
        """Start monitoring keyboard events using pynput"""
        if not pynput_available:
            return False

        def on_press(key):
            if self.stop_flag:
                return False  # Stop listener
            key_char = self._pynput_key_to_char(key)
            if key_char and (len(key_char) == 1 or key_char in PYNPUT_KEY_MAP.values()):
                self.key_pressed.emit(key_char)

        def on_release(key):
            if self.stop_flag:
                return False  # Stop listener
            key_char = self._pynput_key_to_char(key)
            if key_char and (len(key_char) == 1 or key_char in PYNPUT_KEY_MAP.values()):
                self.key_released.emit(key_char)

        self._pynput_listener = pynput_keyboard.Listener(on_press=on_press, on_release=on_release)
        self._pynput_listener.start()
        return True

    @override
    def stop(self):
        """Stop monitoring keyboard events"""
        self.stop_flag = True

        if self._pynput_listener:
            self._pynput_listener.stop()
            self._pynput_listener = None
