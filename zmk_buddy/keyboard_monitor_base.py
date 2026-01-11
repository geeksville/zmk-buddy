"""
Base class for keyboard monitoring implementations.

This module defines the abstract interface that all keyboard monitors must implement.
"""

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class KeyboardMonitorBase(QObject):
    """Base class for keyboard monitoring implementations.

    Subclasses should implement platform-specific keyboard event capture
    (e.g., evdev on Linux, pynput on Windows/macOS).
    """

    key_pressed: Signal = Signal(str)
    key_released: Signal = Signal(str)

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
