"""Live keymap visualization using PySide6 Qt GUI.

This module provides the main GUI application for displaying keyboard layouts
and tracking keypresses in real-time.
"""

import asyncio
import gc
import logging
import platform
import sys
import warnings
from argparse import Namespace
from datetime import datetime
from io import StringIO
from pathlib import Path
from threading import Thread
from typing import TYPE_CHECKING, override
import xml.etree.ElementTree as ET

import yaml

from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QGraphicsOpacityEffect
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtGui import QCloseEvent, QKeyEvent, QPainter, QShowEvent, QPaintEvent, QColor, QMouseEvent, QIcon, QPixmap
from PySide6.QtCore import QSize, Qt, QPoint, QTimer, Signal

from keymap_drawer.config import Config
from keymap_drawer.draw import KeymapDrawer

from zmk_buddy.learning import LearningTracker
from zmk_buddy.keyboard_monitor_base import KeyboardMonitorBase

if TYPE_CHECKING:
    from zmk_buddy.zmk_client import ScannerAPI, ZMKStatusAdvertisement

logger = logging.getLogger(__name__)

# Suppress known Qt/X11 socket resource warnings
warnings.filterwarnings("ignore", category=ResourceWarning, message=".*unclosed.*socket.*X11.*")


def create_keyboard_monitor() -> KeyboardMonitorBase | None:
    """
    Create the best available keyboard monitor for the current platform.

    On Linux: Prefers evdev for direct input device access (more reliable)
    On Windows/macOS: Uses pynput for global keyboard monitoring
    Falls back to pynput on Linux if evdev is unavailable

    Returns:
        A KeyboardMonitorBase instance, or None if no backend is available
    """
    from zmk_buddy.evdev import EvdevKeyboardMonitor, evdev_available
    from zmk_buddy.pynput_monitor import PynputKeyboardMonitor, pynput_available

    current_platform = platform.system()

    # On Linux, prefer evdev (more reliable, direct access)
    if current_platform == "Linux" and evdev_available:
        evdev_monitor = EvdevKeyboardMonitor()
        if evdev_monitor.start():
            logger.info("Using evdev backend for keyboard monitoring (Linux)")
            return evdev_monitor

    # Fall back to pynput (works on Windows, macOS, and as Linux fallback)
    if pynput_available:
        pynput_monitor = PynputKeyboardMonitor()
        if pynput_monitor.start():
            logger.info(f"Using pynput backend for keyboard monitoring ({current_platform})")
            return pynput_monitor

    logger.error("No keyboard monitoring backend available!")
    return None


def create_icon() -> QIcon:
    """
    Create a ZMK logo icon for the window titlebar.

    Returns:
        A QIcon containing the ZMK logo, or a fallback icon if loading fails
    """
    # Load the ZMK logo from local assets
    logo_path = Path(__file__).parent / "assets" / "zmk-logo.png"

    pixmap = QPixmap(str(logo_path))
    assert not pixmap.isNull()

    # Scale to appropriate titlebar size if needed
    if pixmap.width() > 32 or pixmap.height() > 32:
        pixmap = pixmap.scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    return QIcon(pixmap)


# Window visibility timeout in seconds
KEYPRESS_VIEW_SECS = 2.5

# Background transparency (0.0 = fully opaque, 1.0 = fully transparent)
TRANSPARENCY = 0.80

# SVG scaling factor for window size
SVG_SCALE = 0.75

# Opacity for learned keys (0.0 = invisible, 1.0 = fully visible)
LEARNED_KEY_OPACITY = 0.20

# Map Qt key codes to SVG labels
QT_KEY_MAP = {
    Qt.Key.Key_Shift: "Shift",
    Qt.Key.Key_Control: "Control",
    Qt.Key.Key_Alt: "Alt",
    Qt.Key.Key_AltGr: "AltGr",
    Qt.Key.Key_Meta: "Meta",
    Qt.Key.Key_Super_L: "Meta",
    Qt.Key.Key_Super_R: "Meta",
    Qt.Key.Key_CapsLock: "Caps",
    Qt.Key.Key_Tab: "Tab",
    Qt.Key.Key_Return: "Enter",
    Qt.Key.Key_Enter: "Enter",
    Qt.Key.Key_Space: "Space",
    Qt.Key.Key_Backspace: "Bckspc",
    Qt.Key.Key_Delete: "Delete",
    Qt.Key.Key_Escape: "Esc",
}


class SvgWidget(QWidget):
    """Custom widget for rendering SVG with high quality

    Note: Qt's SVG renderer has known limitations with some CSS properties
    (e.g., dominant-baseline) compared to browser rendering. Text positioning
    may differ slightly from browser-rendered SVGs.
    """

    renderer: QSvgRenderer
    svg_content: str
    svg_tree: ET.ElementTree
    svg_root: ET.Element
    held_keys: set[str]
    learned_keys: set[str]  # Keys that have been learned

    def __init__(self, svg_content: str):
        super().__init__()
        self.svg_content = svg_content
        self.held_keys = set()
        self.learned_keys = set()  # Initialize empty, will be updated later

        # Enable transparent background for the widget
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # Parse the SVG XML from string
        self.svg_root = ET.fromstring(svg_content)
        self.svg_tree = ET.ElementTree(self.svg_root)

        # Load initial SVG
        self.renderer = QSvgRenderer(svg_content.encode("utf-8"))

        # Set a fixed size based on the SVG's default size, scaled
        svg_size = self.renderer.defaultSize()
        scaled_size = QSize(int(svg_size.width() * SVG_SCALE), int(svg_size.height() * SVG_SCALE))
        self.setFixedSize(scaled_size)

    @override
    def paintEvent(self, event: QPaintEvent | None) -> None:
        """Custom paint event with high-quality rendering"""
        painter = QPainter(self)

        # Fill background with transparency
        alpha = int(255 * (1 - TRANSPARENCY))
        painter.fillRect(self.rect(), QColor(128, 128, 128, alpha))

        # Enable all quality rendering hints
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.RenderHint.LosslessImageRendering)

        # Render the SVG
        self.renderer.render(painter)

    @override
    def sizeHint(self) -> QSize:
        """Return the preferred size"""
        return self.renderer.defaultSize()

    def find_key_rects(self, key_text: str) -> list[ET.Element]:
        """Find all rect elements for a given key text (e.g., both left and right Shift)"""
        # Register namespace to avoid ns0 prefixes
        ET.register_namespace("", "http://www.w3.org/2000/svg")

        rects = []
        # Normalize key text for case-insensitive comparison
        key_text_lower = key_text.lower()

        # Search for text elements with class "key" (including "key tap" and "key shifted")
        for text_elem in self.svg_root.iter("{http://www.w3.org/2000/svg}text"):
            class_attr = text_elem.get("class", "")

            # Check if this is a key-related text element
            if "key" in class_attr:
                # Check direct text content (case-insensitive)
                if text_elem.text and text_elem.text.strip().lower() == key_text_lower:
                    rect = self._get_rect_from_text_element(text_elem)
                    if rect is not None:
                        rects.append(rect)

        return rects

    def _get_rect_from_text_element(self, text_elem: ET.Element) -> ET.Element | None:
        """Get the rect element from a text element's parent group"""
        parent = self._find_parent(self.svg_root, text_elem)
        if parent is not None:
            # Find rect in the parent group
            for rect in parent.findall("{http://www.w3.org/2000/svg}rect"):
                return rect
        return None

    def _find_parent(self, root: ET.Element, child: ET.Element) -> ET.Element | None:
        """Find the parent of a given element"""
        for parent in root.iter():
            if child in list(parent):
                return parent
        return None

    def update_held_keys(self, key_text: str, is_held: bool) -> None:
        """Update the held state of a key (applies to all matching keys)"""
        rects = self.find_key_rects(key_text)
        if not rects:
            logger.warning(f"No image found for key: {key_text}")
            return

        # Update all matching rects
        for rect in rects:
            class_attr = rect.get("class", "")
            classes = set(class_attr.split())

            if is_held:
                classes.add("held")
            else:
                classes.discard("held")

            # Update the class attribute
            rect.set("class", " ".join(sorted(classes)))

        # Update held keys tracking
        if is_held:
            self.held_keys.add(key_text)
        else:
            self.held_keys.discard(key_text)

    def update_shift_labels(self) -> None:
        """Toggle between tap and shifted labels based on whether Shift is held"""
        # Check if shift is currently held (case-insensitive)
        shift_held = any(k.lower() == "shift" for k in self.held_keys)

        # Find all groups that contain both tap and shifted labels
        for group in self.svg_root.iter("{http://www.w3.org/2000/svg}g"):
            # Look for text elements with "key tap" and "key shifted" classes
            tap_elem = None
            shifted_elem = None

            for text_elem in group.findall("{http://www.w3.org/2000/svg}text"):
                class_attr = text_elem.get("class", "")
                if "key tap" in class_attr:
                    tap_elem = text_elem
                elif "key shifted" in class_attr:
                    shifted_elem = text_elem

            # If both elements exist, toggle visibility
            if tap_elem is not None and shifted_elem is not None:
                if shift_held:
                    # Show shifted, hide tap
                    tap_elem.set("opacity", "0")
                    shifted_elem.set("opacity", "1")
                    # Fix y coordinate to 0 for Qt compatibility
                    shifted_elem.set("y", "0")
                else:
                    # Show tap, hide shifted
                    tap_elem.set("opacity", "1")
                    shifted_elem.set("opacity", "0")

    def _log_svg(self, svg_content: str) -> None:
        """Save SVG to debug directory if logging level is DEBUG.

        Keeps only the last 4 SVG files in /tmp/buddy_svg/
        """
        if not logger.isEnabledFor(logging.DEBUG):
            return

        # Create directory if it doesn't exist
        debug_dir = Path("/tmp/buddy_svg")
        debug_dir.mkdir(exist_ok=True)

        # Generate timestamp-based filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        svg_path = debug_dir / f"{timestamp}.svg"

        # Write SVG content
        svg_path.write_text(svg_content, encoding="utf-8")
        logger.debug(f"Saved SVG to {svg_path}")

        # Clean up old files, keeping only the last 4
        svg_files = sorted(debug_dir.glob("*.svg"))
        if len(svg_files) > 4:
            for old_file in svg_files[:-4]:
                old_file.unlink()
                # logger.debug(f"Removed old SVG file: {old_file}")

    def _reload_svg(self) -> None:
        """Reload the SVG renderer from the modified tree and trigger repaint"""
        # Register namespace before converting to string
        ET.register_namespace("", "http://www.w3.org/2000/svg")
        ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")

        # Apply learned key dimming before converting to string
        # This ensures dimming is applied/removed correctly across all reloads
        self._apply_dimming_to_tree()

        # Reload the SVG from the modified tree
        svg_bytes = ET.tostring(self.svg_root, encoding="unicode")

        # Log SVG for debugging if enabled
        self._log_svg(svg_bytes)

        _ = self.renderer.load(svg_bytes.encode("utf-8"))

        # Trigger repaint
        self.update()

    def update_key_state(self, key_text: str, is_held: bool) -> None:
        """Update key highlighting and shift label display"""
        # Update key highlighting
        self.update_held_keys(key_text, is_held)

        # Update shift label visibility
        self.update_shift_labels()

        # Reload and repaint
        self._reload_svg()

    def set_learned_keys(self, learned_keys: set[str]) -> None:
        """Set the learned keys that should be dimmed.

        Args:
            learned_keys: Set of key labels that are considered learned
        """
        self.learned_keys = learned_keys
        # logger.debug(f"Updated learned keys: {learned_keys}")

    def _apply_dimming_to_tree(self) -> None:
        """Apply opacity dimming to learned keys in the SVG tree.

        This is called automatically by _reload_svg.
        """
        dimmed_count = 0

        # Find all key groups and apply/remove opacity based on learned status
        for group in self.svg_root.iter("{http://www.w3.org/2000/svg}g"):
            class_attr = group.get("class", "")

            # Check if this is a key group
            if "key" not in class_attr:
                continue

            # Find text elements to determine the key label
            for text_elem in group.findall("{http://www.w3.org/2000/svg}text"):
                text_class = text_elem.get("class", "")

                # Check tap labels (main key labels)
                if "key tap" in text_class or text_class == "key":
                    key_text = text_elem.text
                    if key_text:
                        key_lower = key_text.strip().lower()
                        if key_lower in self.learned_keys:
                            # Apply opacity to the entire key group
                            group.set("opacity", str(LEARNED_KEY_OPACITY))
                            dimmed_count += 1
                        else:
                            # Remove opacity if previously set (key no longer learned)
                            if "opacity" in group.attrib:
                                del group.attrib["opacity"]
                        break

        if dimmed_count > 0:
            logger.debug(f"Applied dimming to {dimmed_count} keys")


class KeymapWindow(QMainWindow):
    """Main window for displaying the keymap SVG"""

    # Signal for thread-safe layer changes
    layer_change_requested = Signal(str)

    svg_widget: SvgWidget
    drag_position: QPoint | None
    keyboard_monitor: "KeyboardMonitorBase | None"
    hide_timer: QTimer
    held_keys: set[str]
    yaml_data: dict
    config: Config
    layer_names: list[str]
    current_layer_index: int
    learning_tracker: LearningTracker
    zmk_scanner: "ScannerAPI | None"
    scanner_thread: Thread | None
    scanner_loop: asyncio.AbstractEventLoop | None

    def __init__(
        self, yaml_data: dict, config: Config, testing_mode: bool = False, zmk_scanner: "ScannerAPI | None" = None
    ):
        super().__init__()
        self.setWindowTitle("ZMK Buddy")

        # Set window icon
        self.setWindowIcon(create_icon())

        # Store ZMK scanner reference
        self.zmk_scanner = zmk_scanner
        self.scanner_thread = None
        self.scanner_loop = None

        # Initialize learning tracker
        self.learning_tracker = LearningTracker(testing_mode=testing_mode)

        # Store YAML data and config for layer regeneration
        self.yaml_data = yaml_data
        self.config = config

        # Get list of layer names and start with first layer
        self.layer_names = list(yaml_data.get("layers", {}).keys())
        self.current_layer_index = 0

        # Or this to hide title bar as well
        # self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)

        # Keep window on top and allow mouse clicks to pass through
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowTransparentForInput)

        # Enable transparent background for the window
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # Generate initial SVG and create widget
        svg_content = self._render_current_layer()
        self.svg_widget = SvgWidget(svg_content)

        # Apply learned key dimming
        self._apply_learned_dimming()

        self.setCentralWidget(self.svg_widget)

        # Use QGraphicsOpacityEffect for Wayland compatibility
        self.opacity_effect: QGraphicsOpacityEffect = QGraphicsOpacityEffect(self)
        self.opacity_effect.setOpacity(1.0)
        self.svg_widget.setGraphicsEffect(self.opacity_effect)

        # Resize window to fit content
        self.adjustSize()

        # Track drag position for moving the window
        self.drag_position = None

        # Keyboard monitor for global events
        self.keyboard_monitor = None

        # Timer to hide window after inactivity
        self.hide_timer = QTimer(self)
        _ = self.hide_timer.timeout.connect(self.on_hide_timeout)  # pylint: disable=no-member
        self.hide_timer.setSingleShot(True)

        # Track currently held keys
        self.held_keys = set()

        # Connect layer change signal
        _ = self.layer_change_requested.connect(self.set_layer)

        svg_size = self.svg_widget.size()
        logger.info(f"Window created with size: {svg_size.width()}x{svg_size.height()}")
        if self.layer_names:
            logger.info(f"Showing layer: {self.layer_names[self.current_layer_index]}")
        logger.info("Press 'y' to cycle layers, 'x' to exit. Drag window to reposition it.")

    def _render_current_layer(self) -> str:
        """Render SVG for the current layer."""
        if not self.layer_names:
            # No layers, render empty
            return render_svg(self.yaml_data, self.config)

        layer_name = self.layer_names[self.current_layer_index]
        return render_svg(self.yaml_data, self.config, layer_name)

    def _apply_learned_dimming(self) -> None:
        """Apply opacity dimming to learned keys in the current SVG widget."""
        learned_keys = self.learning_tracker.get_learned_keys()
        if learned_keys:
            logger.info(f"Dimming {len(learned_keys)} learned keys: {learned_keys}")
        else:
            logger.debug("No learned keys to dim")

        # Set the learned keys in the widget (will be applied on next reload)
        self.svg_widget.set_learned_keys(learned_keys)
        self.svg_widget._reload_svg()

    def next_layer(self) -> None:
        """Cycle to the next layer and regenerate the display."""
        if not self.layer_names:
            return

        # Move to next layer (with wraparound)
        self.current_layer_index = (self.current_layer_index + 1) % len(self.layer_names)
        layer_name = self.layer_names[self.current_layer_index]
        logger.info(f"Switching to layer: {layer_name}")

        self._refresh_layer_display()

    def set_layer(self, name: str) -> None:
        """Switch to a specific layer by name.

        Args:
            name: The name of the layer to display. If not found, logs a warning.
        """
        if not self.layer_names:
            logger.warning(f"Cannot set layer '{name}': no layers defined")
            return

        # Find the layer index by name (case-insensitive)
        name_lower = name.lower()
        for i, layer_name in enumerate(self.layer_names):
            if layer_name.lower() == name_lower:
                if i != self.current_layer_index:
                    self.current_layer_index = i
                    logger.info(f"Switching to layer: {layer_name}")
                    self._refresh_layer_display()
                return

        logger.warning(f"Layer '{name}' not found. Available: {self.layer_names}")

    def _refresh_layer_display(self) -> None:
        """Refresh the SVG display for the current layer."""
        # Regenerate SVG for current layer
        svg_content = self._render_current_layer()

        # Replace the SVG widget
        old_widget = self.svg_widget
        self.svg_widget = SvgWidget(svg_content)

        # Apply learned key dimming
        self._apply_learned_dimming()

        # Initialize shift labels before first render to fix y coordinates
        self.svg_widget.update_shift_labels()
        self.svg_widget._reload_svg()

        self.setCentralWidget(self.svg_widget)

        # Reapply opacity effect
        self.svg_widget.setGraphicsEffect(self.opacity_effect)

        # Clean up old widget
        old_widget.deleteLater()

        # Resize window to fit new content
        self.adjustSize()

    @override
    def showEvent(self, a0: QShowEvent) -> None:
        """Called when window is shown"""
        super().showEvent(a0)

        # Log learning progress
        logger.info(f"Learning: {self.learning_tracker.get_summary()}")

        # Start ZMK scanner if provided
        if self.zmk_scanner is not None and self.scanner_thread is None:
            self._start_zmk_scanner()

        # Try to start global keyboard monitoring
        self.keyboard_monitor = create_keyboard_monitor()
        if self.keyboard_monitor:
            _ = self.keyboard_monitor.key_pressed.connect(self.on_global_key_press)
            _ = self.keyboard_monitor.key_released.connect(self.on_global_key_release)
            logger.info("Global keyboard monitoring starting - keys captured even when window not focused")
        else:
            logger.warning(
                "Global monitoring unavailable - window must be focused to capture keys (YOU PROBABLY DON'T WANT THIS)"
            )

    def _start_zmk_scanner(self) -> None:
        """Start the ZMK scanner in a background thread."""
        if self.zmk_scanner is None:
            return

        # Register our callback to receive status updates
        self.zmk_scanner.add_callback(self._on_zmk_status)

        def run_scanner():
            """Run the scanner in an asyncio event loop."""
            self.scanner_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.scanner_loop)
            try:
                self.scanner_loop.run_until_complete(self.zmk_scanner.start())
                # Keep the loop running
                self.scanner_loop.run_forever()
            except Exception as e:
                logger.error(f"Error in ZMK scanner thread: {e}")
            finally:
                self.scanner_loop.close()

        self.scanner_thread = Thread(target=run_scanner, daemon=True)
        self.scanner_thread.start()
        logger.info("ZMK BLE scanner started in background thread")

    def _stop_zmk_scanner(self) -> None:
        """Stop the ZMK scanner and clean up the background thread."""
        if self.zmk_scanner is None or self.scanner_loop is None:
            return

        # Unregister our callback
        self.zmk_scanner.remove_callback(self._on_zmk_status)

        try:
            # Schedule the stop coroutine in the scanner's event loop and wait for it
            stop_future = asyncio.run_coroutine_threadsafe(self.zmk_scanner.stop(), self.scanner_loop)

            # Wait for the stop coroutine to complete (with timeout)
            try:
                stop_future.result(timeout=2.0)
                logger.debug("ZMK scanner stop() completed successfully")
            except asyncio.TimeoutError:
                logger.warning("ZMK scanner stop() timed out")
            except Exception as e:
                logger.error(f"Error in ZMK scanner stop(): {e}")

            # Now stop the event loop
            self.scanner_loop.call_soon_threadsafe(self.scanner_loop.stop)

            # Wait for thread to finish (with timeout)
            if self.scanner_thread is not None:
                self.scanner_thread.join(timeout=2.0)
                if self.scanner_thread.is_alive():
                    logger.warning("ZMK scanner thread did not finish within timeout")

            logger.info("ZMK BLE scanner stopped")
        except Exception as e:
            logger.error(f"Error stopping ZMK scanner: {e}")
        finally:
            self.scanner_thread = None
            self.scanner_loop = None

    def _on_zmk_status(self, status: "ZMKStatusAdvertisement") -> None:
        """Handle status updates from the ZMK scanner.

        This is called from the scanner thread, so we use Qt signals
        for thread-safe communication with the main UI thread.

        Args:
            status: The parsed ZMK status advertisement
        """
        # Update layer if it changed
        layer_name = status.layer_name.strip()
        if layer_name:
            logger.debug(f"ZMK status received: requesting layer change to '{layer_name}'")
            # Emit signal for thread-safe UI update
            self.layer_change_requested.emit(layer_name)
        else:
            logger.debug("ZMK status received: empty layer name, ignoring")

    def on_global_key_press(self, key_char: str) -> None:
        """Handle global key press from keyboard monitor"""

        # to facilitate testing check for x and y here and do special things
        # x to exit, y to cycle layers
        if key_char.lower() == "x":
            logger.info("Exiting...")
            _ = self.close()
            return

        if key_char.lower() == "y":
            self.next_layer()
            return

        # Track keypress for learning
        self.learning_tracker.on_key_press(key_char)

        # Update learned keys in widget (for dimming)
        learned_keys = self.learning_tracker.get_learned_keys()
        self.svg_widget.set_learned_keys(learned_keys)

        # Show window and track this key as held
        logger.debug(f"Key press: {key_char}")
        self.held_keys.add(key_char)
        self.show_window_temporarily()
        self.svg_widget.update_key_state(key_char, is_held=True)

    def on_global_key_release(self, key_char: str) -> None:
        """Handle global key release from keyboard monitor"""

        if key_char.lower() == "y":
            self.next_layer()
            return

        # Track key release for learning (currently unused but available)
        self.learning_tracker.on_key_release(key_char)

        self.held_keys.discard(key_char)
        self.svg_widget.update_key_state(key_char, is_held=False)
        # Start hide timer if no keys are held
        if not self.held_keys:
            self.start_hide_timer()

    def show_window_temporarily(self) -> None:
        """Make the window visible and cancel any pending hide timer"""
        self.opacity_effect.setOpacity(1.0)
        self.hide_timer.stop()
        # Raise window to top of stack (especially important on Wayland)
        self.raise_()

    def start_hide_timer(self) -> None:
        """Start timer to hide window after KEYPRESS_VIEW_SECS"""
        self.hide_timer.start(int(KEYPRESS_VIEW_SECS * 1000))

    def on_hide_timeout(self) -> None:
        """Make the window transparent when timer expires"""
        if not self.held_keys:
            self.opacity_effect.setOpacity(0.0)

    @override
    def closeEvent(self, a0: QCloseEvent) -> None:
        """Clean up when window is closed"""
        logger.info("Cleaning up...")

        self.hide_timer.stop()

        # Stop ZMK scanner first (this may take time)
        if self.zmk_scanner is not None:
            self._stop_zmk_scanner()

        # Stop keyboard monitor
        if self.keyboard_monitor:
            self.keyboard_monitor.stop()
            self.keyboard_monitor = None

        # Save learning statistics on clean exit
        try:
            path = self.learning_tracker.save_stats()
            logger.info(f"Saved learning progress: {self.learning_tracker.get_summary()}")
            if path:
                logger.info(f"Learning stats saved to: {path}")
        except Exception as e:
            logger.error(f"Error saving learning stats: {e}")

        super().closeEvent(a0)

        # Additional cleanup to help with Qt resource management
        self.deleteLater()

    @override
    def keyPressEvent(self, a0: QKeyEvent | None) -> None:
        """Handle key press - exit on 'x', cycle layers on 'y', highlight other keys"""
        if a0 is None:
            return

        # Try to map special keys first
        key = a0.key()
        key_char = QT_KEY_MAP.get(Qt.Key(key))
        if not key_char:
            # Fall back to text for regular keys
            key_char = a0.text()

        if key_char:
            self.on_global_key_press(key_char)

    @override
    def keyReleaseEvent(self, a0: QKeyEvent | None) -> None:
        """Handle key release - remove highlight"""
        if a0 is None:
            return

        # Try to map special keys first
        key = a0.key()
        key_char = QT_KEY_MAP.get(Qt.Key(key))
        if not key_char:
            # Fall back to text for regular keys
            key_char = a0.text()

        if key_char and key_char.lower() != "x":
            self.on_global_key_release(key_char)

    @override
    def mousePressEvent(self, a0: QMouseEvent | None) -> None:
        """Handle mouse press to start dragging"""
        if a0 is not None and a0.button() == Qt.MouseButton.LeftButton:
            # On Wayland, use startSystemMove() which is compositor-aware
            # On X11, fall back to manual dragging
            h = self.windowHandle()
            if h and hasattr(h, "startSystemMove"):
                # Try Wayland-native move first
                _ = h.startSystemMove()
            else:
                # Fall back to manual dragging for X11
                self.drag_position = a0.globalPosition().toPoint() - self.frameGeometry().topLeft()
            a0.accept()

    @override
    def mouseMoveEvent(self, a0: QMouseEvent | None) -> None:
        """Handle mouse move to drag the window (X11 only, Wayland uses startSystemMove)"""
        if a0 is not None and a0.buttons() == Qt.MouseButton.LeftButton and self.drag_position is not None:
            self.move(a0.globalPosition().toPoint() - self.drag_position)
            a0.accept()

    @override
    def mouseReleaseEvent(self, a0: QMouseEvent | None) -> None:
        """Handle mouse release to stop dragging"""
        if a0 is not None:
            self.drag_position = None
            a0.accept()


def render_svg(yaml_data: dict, config: Config, layer_name: str | None = None) -> str:
    """Render an SVG from keymap YAML data using KeymapDrawer.

    Args:
        yaml_data: Parsed YAML keymap data
        config: Configuration object for drawing
        layer_name: Optional layer name to display (if None, shows all layers)

    Returns:
        SVG content as a string
    """
    # Extract layout and layers from YAML
    layout = yaml_data.get("layout", {})
    assert layout, "A layout must be specified in the keymap YAML file"

    layers = yaml_data.get("layers", {})
    combos = yaml_data.get("combos", [])

    # Create output stream
    output = StringIO()

    # Create drawer and generate SVG
    drawer = KeymapDrawer(
        config=config,
        out=output,
        layers=layers,
        layout=layout,
        combos=combos,
    )

    # Draw specific layer or all layers
    if layer_name:
        drawer.print_board(draw_layers=[layer_name])
    else:
        drawer.print_board()

    # Get the SVG content
    svg_content = output.getvalue()
    output.close()

    return svg_content


def live(
    args: Namespace, config: Config, scanner: "ScannerAPI | None" = None
) -> None:  # pylint: disable=unused-argument
    """Show a live view of keypresses"""
    # Customize layer label styling by creating a new DrawConfig with modified svg_extra_style
    custom_draw_config = config.draw_config.model_copy(
        update={
            # "dark_mode": "auto", # Doesn't work
            "svg_extra_style": """
                /* Override layer label styling for better visibility */
                text.label {
                    font-size: 24px;
                    fill: #ffffff;
                    stroke: #000000;
                    stroke-width: 2;
                    letter-spacing: 2px;
                }
    """
        }
    )

    # Create a new Config with the modified draw_config
    config = config.model_copy(update={"draw_config": custom_draw_config})

    # Load keymap data
    if hasattr(args, "keymap") and args.keymap:
        # Load custom keymap from file path
        yaml_path = Path(args.keymap)
        if not yaml_path.exists():
            logger.error(f"Keymap YAML file not found at {yaml_path}")
            sys.exit(1)

        logger.info(f"Loading custom keymap from: {yaml_path.absolute()}")
        with open(yaml_path, "r", encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f)
    else:
        # Load default keymap from package resources
        from zmk_buddy.data.keymaps import load_default_keymap

        logger.info("Loading default keymap (miryoku)")
        yaml_data = load_default_keymap()

    # Override layout with --zmk-keyboard if specified
    if hasattr(args, "zmk_keyboard") and args.zmk_keyboard:
        logger.info(f"Using ZMK keyboard layout: {args.zmk_keyboard}")
        # Get existing layout from yaml_data and merge with zmk_keyboard
        keymap_layout = yaml_data.get("layout", {})
        yaml_data["layout"] = {
            "layout_name": keymap_layout.get("layout_name"),
            "zmk_keyboard": args.zmk_keyboard,
        }

    # Create the Qt application
    app = QApplication(sys.argv)

    # Create and show the window
    testing_mode = hasattr(args, "testing") and args.testing
    window = KeymapWindow(yaml_data, config, testing_mode=testing_mode, zmk_scanner=scanner)
    window.show()

    try:
        logger.info("Starting Qt event loop...")
        # Start the event loop
        exit_code = app.exec()

    finally:
        # Ensure proper Qt cleanup
        logger.debug("Cleaning up Qt application...")

        # Force Qt to process all remaining events and deletions
        app.processEvents()

        # Force garbage collection to clean up any remaining references
        del window
        del app

        # Suppress X11 socket warnings (known Qt/X11 integration issue)
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=ResourceWarning, message=".*unclosed.*socket.*X11.*")
            _ = gc.collect()  # Final cleanup

    sys.exit(exit_code)
