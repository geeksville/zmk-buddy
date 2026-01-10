import logging
import platform
import sys
from argparse import Namespace
from datetime import datetime
from io import StringIO
from pathlib import Path
from threading import Thread
from typing import override
import xml.etree.ElementTree as ET

import yaml

from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QGraphicsOpacityEffect
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtGui import QCloseEvent, QKeyEvent, QPainter, QShowEvent, QPaintEvent, QColor, QMouseEvent
from PySide6.QtCore import QSize, Qt, QPoint, Signal, QObject, QTimer

from keymap_drawer.config import Config
from keymap_drawer.draw import KeymapDrawer

from zmk_buddy.learning import LearningTracker

logger = logging.getLogger(__name__)

# Window visibility timeout in seconds
KEYPRESS_VIEW_SECS = 2.5

# Background transparency (0.0 = fully opaque, 1.0 = fully transparent)
TRANSPARENCY = 0.80

# SVG scaling factor for window size
SVG_SCALE = 0.75

# Opacity for learned keys (0.0 = invisible, 1.0 = fully visible)
LEARNED_KEY_OPACITY = 0.20

# Detect platform
CURRENT_PLATFORM = platform.system()  # 'Linux', 'Windows', 'Darwin' (macOS)

# Try to import evdev for Linux global keyboard monitoring
evdev_available = False
if CURRENT_PLATFORM == 'Linux':
    try:
        import evdev
        from evdev import InputDevice, categorize, ecodes
        evdev_available = True
    except ImportError:
        pass

# Try to import pynput for cross-platform keyboard monitoring
pynput_available = False
try:
    from pynput import keyboard as pynput_keyboard
    pynput_available = True
except ImportError:
    pass

# Map evdev key names to SVG labels
EVDEV_KEY_MAP = {
    'leftshift': 'Shift',
    'rightshift': 'Shift',
    'leftctrl': 'Control',
    'rightctrl': 'Control',
    'leftalt': 'Alt',
    'rightalt': 'AltGr',
    'leftmeta': 'Meta',
    'rightmeta': 'Meta',
    'capslock': 'Caps',
    'tab': 'Tab',
    'enter': 'Enter',
    'space': 'Space',
    'backspace': 'Bckspc',
    'delete': 'Delete',
    'esc': 'Esc',
    'escape': 'Esc',
}

# Map pynput special keys to SVG labels (for Windows/macOS)
# These are pynput.keyboard.Key enum values
PYNPUT_KEY_MAP: dict[str, str] = {
    'shift': 'Shift',
    'shift_l': 'Shift',
    'shift_r': 'Shift',
    'ctrl': 'Control',
    'ctrl_l': 'Control',
    'ctrl_r': 'Control',
    'alt': 'Alt',
    'alt_l': 'Alt',
    'alt_r': 'AltGr',
    'alt_gr': 'AltGr',
    'cmd': 'Meta',
    'cmd_l': 'Meta',
    'cmd_r': 'Meta',
    'caps_lock': 'Caps',
    'tab': 'Tab',
    'enter': 'Enter',
    'return': 'Enter',
    'space': 'Space',
    'backspace': 'Bckspc',
    'delete': 'Delete',
    'esc': 'Esc',
}

# Map Qt key codes to SVG labels
QT_KEY_MAP = {
    Qt.Key.Key_Shift: 'Shift',
    Qt.Key.Key_Control: 'Control',
    Qt.Key.Key_Alt: 'Alt',
    Qt.Key.Key_AltGr: 'AltGr',
    Qt.Key.Key_Meta: 'Meta',
    Qt.Key.Key_Super_L: 'Meta',
    Qt.Key.Key_Super_R: 'Meta',
    Qt.Key.Key_CapsLock: 'Caps',
    Qt.Key.Key_Tab: 'Tab',
    Qt.Key.Key_Return: 'Enter',
    Qt.Key.Key_Enter: 'Enter',
    Qt.Key.Key_Space: 'Space',
    Qt.Key.Key_Backspace: 'Bckspc',
    Qt.Key.Key_Delete: 'Delete',
    Qt.Key.Key_Escape: 'Esc',
}


class KeyboardMonitor(QObject):
    """Monitor keyboard events using platform-appropriate backend.
    
    On Linux: Uses evdev for direct access to input devices (preferred, more reliable)
    On Windows/macOS: Uses pynput for global keyboard monitoring
    Falls back to pynput on Linux if evdev is unavailable
    """
    
    key_pressed: Signal = Signal(str)
    key_released: Signal = Signal(str)
    
    def __init__(self):
        super().__init__()
        self.stop_flag: bool = False
        self.my_thread: Thread | None = None
        self._pynput_listener: "pynput_keyboard.Listener | None" = None
        self._backend: str = 'none'
    
    def _find_keyboard_devices_evdev(self) -> list:
        """Find all keyboard devices using evdev (Linux only)"""
        if not evdev_available:
            return []
        
        keyboards = []
        try:
            devices = [InputDevice(path) for path in evdev.list_devices()]
            for device in devices:
                # Look for a device with keyboard capabilities
                caps = device.capabilities()
                if ecodes.EV_KEY in caps and any(
                    key in caps[ecodes.EV_KEY] 
                    for key in [ecodes.KEY_A, ecodes.KEY_B, ecodes.KEY_C]
                ):
                    keyboards.append(device)
        except (PermissionError, OSError) as e:
            logger.error(f"Cannot access input devices: {e}")
            logger.error("Tip: Add your user to the 'input' group with: sudo usermod -a -G input $USER")
            return []
        
        return keyboards
    
    def _start_evdev(self) -> bool:
        """Start monitoring using evdev (Linux)"""
        import time
        import select
        
        def event_loop():
            """Background thread that monitors keyboard events with auto-reconnect"""
            while not self.stop_flag:
                # Try to find all keyboard devices
                devices = self._find_keyboard_devices_evdev()
                
                if not devices:
                    # No keyboard found, wait 10 seconds and try again
                    logger.warning("No keyboard device found, retrying in 10 seconds (Ensure user has access to /dev/input/event*: sudo usermod -aG input $USER)...")
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
                                        if keycode.startswith('KEY_'):
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
        self._backend = 'evdev'
        return True
    
    def _pynput_key_to_char(self, key) -> str | None:
        """Convert a pynput key to a character string for SVG lookup"""
        try:
            # Check if it's a regular character key
            if hasattr(key, 'char') and key.char:
                return key.char
            
            # It's a special key - get its name
            if hasattr(key, 'name'):
                key_name = key.name.lower()
                return PYNPUT_KEY_MAP.get(key_name, key_name)
            
            # Try to get the key value as a string
            key_str = str(key).replace('Key.', '').lower()
            return PYNPUT_KEY_MAP.get(key_str, key_str)
        except Exception:
            return None
    
    def _start_pynput(self) -> bool:
        """Start monitoring using pynput (Windows/macOS/Linux fallback)"""
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
        
        self._pynput_listener = pynput_keyboard.Listener(
            on_press=on_press,
            on_release=on_release
        )
        self._pynput_listener.start()
        self._backend = 'pynput'
        return True
    
    def start(self) -> bool:
        """Start monitoring keyboard events using the best available backend"""
        # On Linux, prefer evdev (more reliable, direct access)
        if CURRENT_PLATFORM == 'Linux' and evdev_available:
            if self._start_evdev():
                logger.info("Using evdev backend for keyboard monitoring (Linux)")
                return True
        
        # Fall back to pynput (works on Windows, macOS, and as Linux fallback)
        if pynput_available:
            if self._start_pynput():
                logger.info(f"Using pynput backend for keyboard monitoring ({CURRENT_PLATFORM})")
                return True
        
        logger.error("No keyboard monitoring backend available!")
        return False
    
    def stop(self):
        """Stop monitoring keyboard events"""
        self.stop_flag = True
        
        if self._pynput_listener:
            self._pynput_listener.stop()
            self._pynput_listener = None
        
        if self.my_thread:
            self.my_thread.join(timeout=1.0)


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
        self.renderer = QSvgRenderer(svg_content.encode('utf-8'))
        
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
        ET.register_namespace('', 'http://www.w3.org/2000/svg')
        
        rects = []
        # Normalize key text for case-insensitive comparison
        key_text_lower = key_text.lower()
        
        # Search for text elements with class "key" (including "key tap" and "key shifted")
        for text_elem in self.svg_root.iter('{http://www.w3.org/2000/svg}text'):
            class_attr = text_elem.get('class', '')
            
            # Check if this is a key-related text element
            if 'key' in class_attr:
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
            for rect in parent.findall('{http://www.w3.org/2000/svg}rect'):
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
            class_attr = rect.get('class', '')
            classes = set(class_attr.split())
            
            if is_held:
                classes.add('held')
            else:
                classes.discard('held')
            
            # Update the class attribute
            rect.set('class', ' '.join(sorted(classes)))
        
        # Update held keys tracking
        if is_held:
            self.held_keys.add(key_text)
        else:
            self.held_keys.discard(key_text)
    
    def update_shift_labels(self) -> None:
        """Toggle between tap and shifted labels based on whether Shift is held"""
        # Check if shift is currently held (case-insensitive)
        shift_held = any(k.lower() == 'shift' for k in self.held_keys)
        
        # Find all groups that contain both tap and shifted labels
        for group in self.svg_root.iter('{http://www.w3.org/2000/svg}g'):
            # Look for text elements with "key tap" and "key shifted" classes
            tap_elem = None
            shifted_elem = None
            
            for text_elem in group.findall('{http://www.w3.org/2000/svg}text'):
                class_attr = text_elem.get('class', '')
                if 'key tap' in class_attr:
                    tap_elem = text_elem
                elif 'key shifted' in class_attr:
                    shifted_elem = text_elem
            
            # If both elements exist, toggle visibility
            if tap_elem is not None and shifted_elem is not None:
                if shift_held:
                    # Show shifted, hide tap
                    tap_elem.set('opacity', '0')
                    shifted_elem.set('opacity', '1')
                    # Fix y coordinate to 0 for Qt compatibility
                    shifted_elem.set('y', '0')
                else:
                    # Show tap, hide shifted
                    tap_elem.set('opacity', '1')
                    shifted_elem.set('opacity', '0')
    
    def _log_svg(self, svg_content: str) -> None:
        """Save SVG to debug directory if logging level is DEBUG.
        
        Keeps only the last 4 SVG files in /tmp/buddy_svg/
        """
        if not logger.isEnabledFor(logging.DEBUG):
            return
        
        # Create directory if it doesn't exist
        debug_dir = Path('/tmp/buddy_svg')
        debug_dir.mkdir(exist_ok=True)
        
        # Generate timestamp-based filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        svg_path = debug_dir / f"{timestamp}.svg"
        
        # Write SVG content
        svg_path.write_text(svg_content, encoding='utf-8')
        logger.debug(f"Saved SVG to {svg_path}")
        
        # Clean up old files, keeping only the last 4
        svg_files = sorted(debug_dir.glob('*.svg'))
        if len(svg_files) > 4:
            for old_file in svg_files[:-4]:
                old_file.unlink()
                # logger.debug(f"Removed old SVG file: {old_file}")
    
    def _reload_svg(self) -> None:
        """Reload the SVG renderer from the modified tree and trigger repaint"""
        # Register namespace before converting to string
        ET.register_namespace('', 'http://www.w3.org/2000/svg')
        ET.register_namespace('xlink', 'http://www.w3.org/1999/xlink')
        
        # Apply learned key dimming before converting to string
        # This ensures dimming is applied/removed correctly across all reloads
        self._apply_dimming_to_tree()
        
        # Reload the SVG from the modified tree
        svg_bytes = ET.tostring(self.svg_root, encoding='unicode')
        
        # Log SVG for debugging if enabled
        self._log_svg(svg_bytes)
        
        _ = self.renderer.load(svg_bytes.encode('utf-8'))
        
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
        for group in self.svg_root.iter('{http://www.w3.org/2000/svg}g'):
            class_attr = group.get('class', '')
            
            # Check if this is a key group
            if 'key' not in class_attr:
                continue
            
            # Find text elements to determine the key label
            for text_elem in group.findall('{http://www.w3.org/2000/svg}text'):
                text_class = text_elem.get('class', '')
                
                # Check tap labels (main key labels)
                if 'key tap' in text_class or text_class == 'key':
                    key_text = text_elem.text
                    if key_text:
                        key_lower = key_text.strip().lower()
                        if key_lower in self.learned_keys:
                            # Apply opacity to the entire key group
                            group.set('opacity', str(LEARNED_KEY_OPACITY))
                            dimmed_count += 1
                        else:
                            # Remove opacity if previously set (key no longer learned)
                            if 'opacity' in group.attrib:
                                del group.attrib['opacity']
                        break
        
        if dimmed_count > 0:
            logger.debug(f"Applied dimming to {dimmed_count} keys")


class KeymapWindow(QMainWindow):
    """Main window for displaying the keymap SVG"""
    
    svg_widget: SvgWidget
    drag_position: QPoint | None
    keyboard_monitor: KeyboardMonitor | None
    hide_timer: QTimer
    held_keys: set[str]
    yaml_data: dict
    config: Config
    layer_names: list[str]
    current_layer_index: int
    learning_tracker: LearningTracker
    
    def __init__(self, yaml_data: dict, config: Config, testing_mode: bool = False):
        super().__init__()
        self.setWindowTitle("Keymap Drawer - Live View")
        
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
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint | 
            Qt.WindowType.WindowTransparentForInput
        )

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
        _ = self.hide_timer.timeout.connect(self.on_hide_timeout)
        self.hide_timer.setSingleShot(True)
        
        # Track currently held keys
        self.held_keys = set()
        
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
        
        # Regenerate SVG for new layer
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
    def showEvent(self, a0: QShowEvent | None) -> None:
        """Called when window is shown"""
        super().showEvent(a0)
        
        # Log learning progress
        logger.info(f"Learning: {self.learning_tracker.get_summary()}")
        
        # Try to start global keyboard monitoring
        if evdev_available:
            self.keyboard_monitor = KeyboardMonitor()
            _ = self.keyboard_monitor.key_pressed.connect(self.on_global_key_press)
            _ = self.keyboard_monitor.key_released.connect(self.on_global_key_release)
            _ = self.keyboard_monitor.start()
            logger.info("Global keyboard monitoring starting - keys captured even when window not focused")
        else:
            logger.warning("Global monitoring unavailable - window must be focused to capture keys (YOU PROBABLY DON'T WANT THIS)")
        
    def on_global_key_press(self, key_char: str) -> None:
        """Handle global key press from keyboard monitor"""
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
    def closeEvent(self, a0: QCloseEvent | None) -> None:
        """Clean up when window is closed"""
        self.hide_timer.stop()
        if self.keyboard_monitor:
            self.keyboard_monitor.stop()
        
        # Save learning statistics on clean exit
        path = self.learning_tracker.save_stats()
        logger.info(f"Saved learning progress: {self.learning_tracker.get_summary()}")
        if path:
            logger.info(f"Learning stats saved to: {path}")
        
        super().closeEvent(a0)

    @override    
    def keyPressEvent(self, a0: QKeyEvent | None) -> None:
        """Handle key press - exit on 'x', cycle layers on 'y', highlight other keys"""
        if a0 is None:
            return
        
        # Try to map special keys first
        key_char = QT_KEY_MAP.get(a0.key())
        if not key_char:
            # Fall back to text for regular keys
            key_char = a0.text()
        
        if key_char and key_char.lower() == 'x':
            logger.info("Exiting...")
            _ = self.close()
            return
        
        if key_char and key_char.lower() == 'y':
            self.next_layer()
            return
        
        if key_char:
            # Track keypress for learning
            self.learning_tracker.on_key_press(key_char)
            
            self.held_keys.add(key_char)
            self.show_window_temporarily()
            self.svg_widget.update_key_state(key_char, is_held=True)
    
    @override
    def keyReleaseEvent(self, a0: QKeyEvent | None) -> None:
        """Handle key release - remove highlight"""
        if a0 is None:
            return
        
        # Try to map special keys first
        key_char = QT_KEY_MAP.get(a0.key())
        if not key_char:
            # Fall back to text for regular keys
            key_char = a0.text()
        
        if key_char and key_char.lower() != 'x':
            # Track key release for learning
            self.learning_tracker.on_key_release(key_char)
            
            self.held_keys.discard(key_char)
            self.svg_widget.update_key_state(key_char, is_held=False)
            # Start hide timer if no keys are held
            if not self.held_keys:
                self.start_hide_timer()
    
    @override
    def mousePressEvent(self, a0: QMouseEvent | None) -> None:
        """Handle mouse press to start dragging"""
        if a0 is not None and a0.button() == Qt.MouseButton.LeftButton:
            # On Wayland, use startSystemMove() which is compositor-aware
            # On X11, fall back to manual dragging
            h = self.windowHandle()
            if h and hasattr(h, 'startSystemMove'):
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

def live(args: Namespace, config: Config) -> None:  # pylint: disable=unused-argument
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
    if hasattr(args, 'keymap') and args.keymap:
        # Load custom keymap from file path
        yaml_path = Path(args.keymap)
        if not yaml_path.exists():
            logger.error(f"Keymap YAML file not found at {yaml_path}")
            sys.exit(1)
        
        logger.info(f"Loading custom keymap from: {yaml_path.absolute()}")
        with open(yaml_path, 'r', encoding='utf-8') as f:
            yaml_data = yaml.safe_load(f)
    else:
        # Load default keymap from package resources
        from zmk_buddy.data.keymaps import load_default_keymap
        logger.info("Loading default keymap (miryoku)")
        yaml_data = load_default_keymap()
    
    # Create the Qt application
    app = QApplication(sys.argv)
    
    # Create and show the window
    testing_mode = hasattr(args, 'testing') and args.testing
    window = KeymapWindow(yaml_data, config, testing_mode=testing_mode)
    window.show()
    
    logger.info("Starting Qt event loop...")
    # Start the event loop
    exit_code = app.exec()
    sys.exit(exit_code)
