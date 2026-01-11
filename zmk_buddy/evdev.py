"""
Evdev-based keyboard monitoring for Linux.

This module provides global keyboard monitoring using the evdev library,
which directly accesses Linux input devices for reliable key event capture.
"""

from evdev.device import InputDevice


import logging
import select
import time
from threading import Thread
from typing import Any, override

from zmk_buddy.keyboard_monitor_base import KeyboardMonitorBase

logger = logging.getLogger(__name__)

# Try to import evdev for Linux global keyboard monitoring
evdev_available = False
try:
    import evdev
    from evdev import InputDevice, categorize, ecodes

    evdev_available = True
except ImportError:
    pass

# Map evdev key names to SVG labels
EVDEV_KEY_MAP = {
    "leftshift": "Shift",
    "rightshift": "Shift",
    "leftctrl": "Control",
    "rightctrl": "Control",
    "leftalt": "Alt",
    "rightalt": "AltGr",
    "leftmeta": "Meta",
    "rightmeta": "Meta",
    "capslock": "Caps",
    "tab": "Tab",
    "enter": "Enter",
    "space": "Space",
    "backspace": "Bckspc",
    "delete": "Delete",
    "esc": "Esc",
    "escape": "Esc",
}


class EvdevKeyboardMonitor(KeyboardMonitorBase):
    """Monitor keyboard events using evdev (Linux only).

    This provides direct access to Linux input devices for reliable
    global keyboard monitoring without requiring X11 or Wayland.
    """

    def __init__(self) -> None:
        super().__init__()
        self.stop_flag: bool = False
        self.my_thread: Thread | None = None

    def _find_keyboard_devices_evdev(self) -> list[InputDevice[str]]:
        """Find all keyboard devices using evdev (Linux only)"""
        if not evdev_available:
            return []

        keyboards: list[InputDevice[str]] = []
        try:
            devices: list[InputDevice[str]] = [InputDevice(path) for path in evdev.list_devices()]
            for device in devices:
                # Look for a device with keyboard capabilities
                caps = device.capabilities()
                if ecodes.EV_KEY in caps and any(
                    key in caps[ecodes.EV_KEY] for key in [ecodes.KEY_A, ecodes.KEY_B, ecodes.KEY_C]
                ):
                    keyboards.append(device)
        except (PermissionError, OSError) as e:
            logger.error(f"Cannot access input devices: {e}")
            logger.error("Tip: Add your user to the 'input' group with: sudo usermod -a -G input $USER")
            return []

        return keyboards

    @override
    def start(self) -> bool:
        """Start monitoring keyboard events using evdev"""
        if not evdev_available:
            return False

        def event_loop():
            """Background thread that monitors keyboard events with auto-reconnect"""
            while not self.stop_flag:
                # Try to find all keyboard devices
                devices = self._find_keyboard_devices_evdev()

                if not devices:
                    # No keyboard found, wait 10 seconds and try again
                    logger.warning(
                        "No keyboard device found, retrying in 10 seconds (Ensure user has access to /dev/input/event*: sudo usermod -aG input $USER)..."
                    )
                    time.sleep(10)
                    continue

                logger.info(f"Monitoring {len(devices)} keyboard(s): {', '.join(d.name for d in devices)}")

                try:
                    # Create a mapping from file descriptor to device
                    fd_to_device = {dev.fd: dev for dev in devices}

                    while not self.stop_flag:
                        # Use select to wait for events from any device
                        r, _, _ = select.select(fd_to_device.keys(), [], [], 1.0)

                        for fd in r:
                            device = fd_to_device[fd]
                            try:
                                # Read events from this device
                                for event in device.read():
                                    if event.type == ecodes.EV_KEY:
                                        key_event = categorize(event)

                                        # Map keycode to character
                                        keycode = key_event.keycode
                                        if isinstance(keycode, list):
                                            keycode = keycode[0]

                                        # Strip KEY_ prefix and convert to lowercase
                                        if keycode.startswith("KEY_"):
                                            key_name = keycode[4:].lower()

                                            # Check if it's a special key that needs mapping
                                            key_char = EVDEV_KEY_MAP.get(key_name, key_name)

                                            # Only handle single characters or mapped special keys
                                            if len(key_char) == 1 or key_name in EVDEV_KEY_MAP:
                                                if key_event.keystate == key_event.key_down:
                                                    self.key_pressed.emit(key_char)
                                                elif key_event.keystate == key_event.key_up:
                                                    self.key_released.emit(key_char)
                            except (OSError, IOError) as e:
                                logger.warning(f"Error reading from {device.name}: {e}")
                                raise
                except Exception as e:
                    logger.warning(f"Keyboard(s) disconnected: {e}")
                finally:
                    for device in devices:
                        try:
                            device.close()
                        except Exception:
                            pass

                if not self.stop_flag:
                    logger.info("Attempting to reconnect in 10 seconds...")
                    time.sleep(10)

        self.my_thread = Thread(target=event_loop, daemon=True)
        self.my_thread.start()
        return True

    @override
    def stop(self):
        """Stop monitoring keyboard events"""
        self.stop_flag = True

        if self.my_thread:
            self.my_thread.join(timeout=1.0)
