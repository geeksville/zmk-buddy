"""Live keymap visualization using GTK4 and WebKit.

This module provides the main GUI application for displaying keyboard layouts
and tracking keypresses in real-time using WebKit for high-quality SVG rendering.
"""

# pylint: disable=wrong-import-position

import asyncio
import logging
import platform
import sys
from argparse import Namespace
from datetime import datetime
from io import StringIO
from pathlib import Path
from threading import Thread
from typing import TYPE_CHECKING
import xml.etree.ElementTree as ET

import yaml

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("WebKit", "6.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, GLib, WebKit  # noqa: E402

from keymap_drawer.config import Config  # noqa: E402
from keymap_drawer.draw import KeymapDrawer  # noqa: E402

from zmk_buddy.learning import LearningTracker  # noqa: E402
from zmk_buddy.keyboard_monitor_base import KeyboardMonitorBase  # noqa: E402

if TYPE_CHECKING:
    from zmk_buddy.zmk_client import ScannerAPI, ZMKStatusAdvertisement

logger = logging.getLogger(__name__)


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


# Window visibility timeout in seconds
KEYPRESS_VIEW_SECS = 2.5

# Background transparency (0.0 = fully transparent, 1.0 = fully opaque)
TRANSPARENCY = 0.20

# SVG scaling factor for window size
SVG_SCALE = 0.75

# Opacity for learned keys (0.0 = invisible, 1.0 = fully visible)
LEARNED_KEY_OPACITY = 0.20


class KeymapWindow(Gtk.ApplicationWindow):
    """Main window for displaying the keymap SVG using WebKit."""

    def __init__(
        self,
        app: Gtk.Application,
        yaml_data: dict,
        config: Config,
        testing_mode: bool = False,
        zmk_scanner: "ScannerAPI | None" = None,
    ):
        super().__init__(application=app)
        self.set_title("ZMK Buddy")

        # Set window icon (icon theme path is set up by the app)
        self.set_icon_name("zmk-logo")

        # Store references
        self.yaml_data = yaml_data
        self.config = config
        self.zmk_scanner = zmk_scanner
        self.scanner_thread: Thread | None = None
        self.scanner_loop: asyncio.AbstractEventLoop | None = None

        # Initialize learning tracker
        self.learning_tracker = LearningTracker(testing_mode=testing_mode)

        # Get list of layer names and start with first layer
        self.layer_names = list(yaml_data.get("layers", {}).keys())
        self.current_layer_index = 0

        # SVG state tracking
        self.svg_content = ""
        self.svg_root: ET.Element | None = None
        self.held_keys: set[str] = set()
        self.learned_keys: set[str] = set()

        # Keyboard monitor
        self.keyboard_monitor: KeyboardMonitorBase | None = None

        # Hide timer
        self.hide_timer_id: int | None = None

        # Setup window properties for transparency and always-on-top
        self._setup_window_properties()

        # Create WebKit view for SVG rendering
        self.webview = WebKit.WebView()
        self.webview.set_vexpand(True)
        self.webview.set_hexpand(True)

        # Make WebKit background fully transparent
        self.webview.set_background_color(Gdk.RGBA(red=0.0, green=0.0, blue=0.0, alpha=0.0))

        # Set content
        self.set_child(self.webview)

        # Generate and display initial SVG
        self._refresh_layer_display()

        # Connect signals
        self.connect("close-request", self._on_close_request)
        self.connect("realize", self._on_realize)

        # Set initial size based on SVG
        self.set_default_size(600, 400)

        logger.info("Press 'y' to cycle layers, 'x' to exit.")

    def _setup_window_properties(self) -> None:
        """Configure window for transparency and always-on-top behavior."""
        # Request window to stay on top (may not work on all compositors)
        self.set_decorated(True)

        # Enable transparency via CSS
        css_provider = Gtk.CssProvider()
        css_provider.load_from_string(
            """
            window {
                background-color: transparent;
            }
            """
        )
        # Apply CSS to the window
        self.get_style_context().add_provider(css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def _on_realize(self, widget: Gtk.Widget) -> None:
        """Called when window is realized - start monitors and configure surface."""
        # Log learning progress
        logger.info(f"Learning: {self.learning_tracker.get_summary()}")

        # Start ZMK scanner if provided
        if self.zmk_scanner is not None and self.scanner_thread is None:
            self._start_zmk_scanner()

        # Start keyboard monitoring
        self.keyboard_monitor = create_keyboard_monitor()
        if self.keyboard_monitor:
            self.keyboard_monitor.connect("key-pressed", self._on_key_pressed)
            self.keyboard_monitor.connect("key-released", self._on_key_released)
            logger.info("Global keyboard monitoring started")
        else:
            logger.warning("Global keyboard monitoring unavailable")

        # Try to set always-on-top after window is realized
        surface = self.get_surface()
        if surface and hasattr(surface, "set_keep_above"):
            surface.set_keep_above(True)

    def _render_current_layer(self) -> str:
        """Render SVG for the current layer."""
        if not self.layer_names:
            return render_svg(self.yaml_data, self.config)

        layer_name = self.layer_names[self.current_layer_index]
        return render_svg(self.yaml_data, self.config, layer_name)

    def _refresh_layer_display(self) -> None:
        """Refresh the SVG display for the current layer."""
        self.svg_content = self._render_current_layer()

        # Parse SVG for manipulation
        self.svg_root = ET.fromstring(self.svg_content)

        # Apply learned key dimming
        self.learned_keys = self.learning_tracker.get_learned_keys()
        self._apply_dimming_to_tree()

        # Update the WebView
        self._update_webview()

        if self.layer_names:
            logger.info(f"Showing layer: {self.layer_names[self.current_layer_index]}")

    def _update_webview(self) -> None:
        """Update the WebView with the current SVG content."""
        if self.svg_root is None:
            return

        # Convert SVG tree back to string
        ET.register_namespace("", "http://www.w3.org/2000/svg")
        ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
        svg_string = ET.tostring(self.svg_root, encoding="unicode")

        # Log for debugging
        self._log_svg(svg_string)

        # Create HTML wrapper with transparent background and proper scaling
        # Use TRANSPARENCY constant for the SVG background opacity
        bg_opacity = TRANSPARENCY
        html = f"""<!DOCTYPE html>
<html>
<head>
    <style>
        html, body {{
            margin: 0;
            padding: 0;
            background: transparent;
            overflow: hidden;
        }}
        svg {{
            max-width: 100%;
            max-height: 100vh;
            display: block;
            margin: auto;
            background-color: rgba(128, 128, 128, {bg_opacity});
            border-radius: 8px;
        }}
        /* Style for held keys */
        rect.held {{
            fill: #ffcc00 !important;
            stroke: #ff9900 !important;
        }}
    </style>
</head>
<body>
{svg_string}
</body>
</html>"""

        # Load the HTML content
        self.webview.load_html(html, "file:///")

    def _apply_dimming_to_tree(self) -> None:
        """Apply opacity dimming to learned keys in the SVG tree."""
        if self.svg_root is None:
            return

        dimmed_count = 0

        for group in self.svg_root.iter("{http://www.w3.org/2000/svg}g"):
            class_attr = group.get("class", "")

            if "key" not in class_attr:
                continue

            for text_elem in group.findall("{http://www.w3.org/2000/svg}text"):
                text_class = text_elem.get("class", "")

                if "key tap" in text_class or text_class == "key":
                    key_text = text_elem.text
                    if key_text:
                        key_lower = key_text.strip().lower()
                        if key_lower in self.learned_keys:
                            group.set("opacity", str(LEARNED_KEY_OPACITY))
                            dimmed_count += 1
                        else:
                            if "opacity" in group.attrib:
                                del group.attrib["opacity"]
                        break

        if dimmed_count > 0:
            logger.debug(f"Applied dimming to {dimmed_count} keys")

    def _update_key_state(self, key_text: str, is_held: bool) -> None:
        """Update the held state of a key in the SVG."""
        if self.svg_root is None:
            return

        key_text_lower = key_text.lower()

        # Find and update matching key rects
        for text_elem in self.svg_root.iter("{http://www.w3.org/2000/svg}text"):
            class_attr = text_elem.get("class", "")
            if "key" in class_attr:
                if text_elem.text and text_elem.text.strip().lower() == key_text_lower:
                    # Find parent group's rect
                    parent = self._find_parent(self.svg_root, text_elem)
                    if parent is not None:
                        for rect in parent.findall("{http://www.w3.org/2000/svg}rect"):
                            classes = set(rect.get("class", "").split())
                            if is_held:
                                classes.add("held")
                            else:
                                classes.discard("held")
                            rect.set("class", " ".join(sorted(classes)))

        # Track held keys
        if is_held:
            self.held_keys.add(key_text)
        else:
            self.held_keys.discard(key_text)

        # Update display
        self._update_webview()

    def _find_parent(self, root: ET.Element, child: ET.Element) -> ET.Element | None:
        """Find the parent of a given element."""
        for parent in root.iter():
            if child in list(parent):
                return parent
        return None

    def _log_svg(self, svg_content: str) -> None:
        """Save SVG to debug directory if logging level is DEBUG."""
        if not logger.isEnabledFor(logging.DEBUG):
            return

        debug_dir = Path("/tmp/buddy_svg")
        debug_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        svg_path = debug_dir / f"{timestamp}.svg"
        svg_path.write_text(svg_content, encoding="utf-8")
        logger.debug(f"Saved SVG to {svg_path}")

        # Clean up old files
        svg_files = sorted(debug_dir.glob("*.svg"))
        if len(svg_files) > 4:
            for old_file in svg_files[:-4]:
                old_file.unlink()

    def next_layer(self) -> None:
        """Cycle to the next layer."""
        if not self.layer_names:
            return

        self.current_layer_index = (self.current_layer_index + 1) % len(self.layer_names)
        logger.info(f"Switching to layer: {self.layer_names[self.current_layer_index]}")
        self._refresh_layer_display()

    def set_layer(self, name: str) -> None:
        """Switch to a specific layer by name."""
        if not self.layer_names:
            logger.warning(f"Cannot set layer '{name}': no layers defined")
            return

        name_lower = name.lower()
        for i, layer_name in enumerate(self.layer_names):
            if layer_name.lower() == name_lower:
                if i != self.current_layer_index:
                    self.current_layer_index = i
                    logger.info(f"Switching to layer: {layer_name}")
                    self._refresh_layer_display()
                return

        logger.warning(f"Layer '{name}' not found. Available: {self.layer_names}")

    def _on_key_pressed(self, monitor: KeyboardMonitorBase, key_char: str) -> None:
        """Handle global key press."""
        # Special keys for testing
        if key_char.lower() == "x":
            logger.info("Exiting...")
            self.close()
            return

        if key_char.lower() == "y":
            self.next_layer()
            return

        # Track for learning
        self.learning_tracker.on_key_press(key_char)
        self.learned_keys = self.learning_tracker.get_learned_keys()

        # Update display
        logger.debug(f"Key press: {key_char}")
        self._update_key_state(key_char, is_held=True)
        self._show_window_temporarily()

    def _on_key_released(self, monitor: KeyboardMonitorBase, key_char: str) -> None:
        """Handle global key release."""
        if key_char.lower() == "y":
            return

        self.learning_tracker.on_key_release(key_char)
        self._update_key_state(key_char, is_held=False)

        if not self.held_keys:
            self._start_hide_timer()

    def _show_window_temporarily(self) -> None:
        """Show the window and cancel any pending hide timer."""
        if self.hide_timer_id is not None:
            GLib.source_remove(self.hide_timer_id)
            self.hide_timer_id = None

        self.set_opacity(1.0)
        self.present()

    def _start_hide_timer(self) -> None:
        """Start timer to fade out window after inactivity."""
        if self.hide_timer_id is not None:
            GLib.source_remove(self.hide_timer_id)

        self.hide_timer_id = GLib.timeout_add(int(KEYPRESS_VIEW_SECS * 1000), self._on_hide_timeout)

    def _on_hide_timeout(self) -> bool:
        """Fade out window when timer expires."""
        if not self.held_keys:
            self.set_opacity(0.0)
        self.hide_timer_id = None
        return False  # Don't repeat

    def _start_zmk_scanner(self) -> None:
        """Start the ZMK scanner in a background thread."""
        if self.zmk_scanner is None:
            return

        self.zmk_scanner.add_callback(self._on_zmk_status)

        def run_scanner():
            self.scanner_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.scanner_loop)
            try:
                self.scanner_loop.run_until_complete(self.zmk_scanner.start())
                self.scanner_loop.run_forever()
            except Exception as e:
                logger.error(f"Error in ZMK scanner thread: {e}")
            finally:
                self.scanner_loop.close()

        self.scanner_thread = Thread(target=run_scanner, daemon=True)
        self.scanner_thread.start()
        logger.info("ZMK BLE scanner started in background thread")

    def _stop_zmk_scanner(self) -> None:
        """Stop the ZMK scanner."""
        if self.zmk_scanner is None or self.scanner_loop is None:
            return

        self.zmk_scanner.remove_callback(self._on_zmk_status)

        try:
            stop_future = asyncio.run_coroutine_threadsafe(self.zmk_scanner.stop(), self.scanner_loop)
            try:
                stop_future.result(timeout=2.0)
            except asyncio.TimeoutError:
                logger.warning("ZMK scanner stop() timed out")
            except Exception as e:
                logger.error(f"Error in ZMK scanner stop(): {e}")

            self.scanner_loop.call_soon_threadsafe(self.scanner_loop.stop)

            if self.scanner_thread is not None:
                self.scanner_thread.join(timeout=2.0)

            logger.info("ZMK BLE scanner stopped")
        except Exception as e:
            logger.error(f"Error stopping ZMK scanner: {e}")
        finally:
            self.scanner_thread = None
            self.scanner_loop = None

    def _on_zmk_status(self, status: "ZMKStatusAdvertisement") -> None:
        """Handle status updates from ZMK scanner (thread-safe)."""
        layer_name = status.layer_name.strip()
        if layer_name:
            logger.debug(f"ZMK status received: requesting layer change to '{layer_name}'")
            GLib.idle_add(self.set_layer, layer_name)
        else:
            logger.debug("ZMK status received: empty layer name, ignoring")

    def _on_close_request(self, window: Gtk.Window) -> bool:
        """Clean up when window is closed."""
        logger.info("Cleaning up...")

        if self.hide_timer_id is not None:
            GLib.source_remove(self.hide_timer_id)
            self.hide_timer_id = None

        if self.zmk_scanner is not None:
            self._stop_zmk_scanner()

        if self.keyboard_monitor:
            self.keyboard_monitor.stop()
            self.keyboard_monitor = None

        try:
            path = self.learning_tracker.save_stats()
            logger.info(f"Saved learning progress: {self.learning_tracker.get_summary()}")
            if path:
                logger.info(f"Learning stats saved to: {path}")
        except Exception as e:
            logger.error(f"Error saving learning stats: {e}")

        return False  # Allow window to close


class KeymapApp(Gtk.Application):
    """GTK Application for the keymap viewer."""

    def __init__(
        self,
        yaml_data: dict,
        config: Config,
        testing_mode: bool = False,
        zmk_scanner: "ScannerAPI | None" = None,
    ):
        super().__init__(application_id="org.zmkbuddy.KeymapViewer")
        self.yaml_data = yaml_data
        self.config = config
        self.testing_mode = testing_mode
        self.zmk_scanner = zmk_scanner

        # Set up custom icon theme path for our assets
        self._setup_icon_theme()

    def _setup_icon_theme(self) -> None:
        """Add our assets directory to the icon theme search path."""
        assets_dir = Path(__file__).parent / "assets"
        if assets_dir.exists():
            # Get the default icon theme and add our assets path
            # pylint: disable=no-value-for-parameter
            display = Gdk.Display.get_default()
            if display:
                icon_theme = Gtk.IconTheme.get_for_display(display)
                icon_theme.add_search_path(str(assets_dir))
                logger.debug(f"Added icon theme path: {assets_dir}")

    def do_activate(self) -> None:  # pylint: disable=arguments-differ
        """Create and show the main window."""
        window = KeymapWindow(
            self,
            self.yaml_data,
            self.config,
            self.testing_mode,
            self.zmk_scanner,
        )
        window.present()


def render_svg(yaml_data: dict, config: Config, layer_name: str | None = None) -> str:
    """Render an SVG from keymap YAML data using KeymapDrawer.

    Args:
        yaml_data: Parsed YAML keymap data
        config: Configuration object for drawing
        layer_name: Optional layer name to display (if None, shows all layers)

    Returns:
        SVG content as a string
    """
    layout = yaml_data.get("layout", {})
    assert layout, "A layout must be specified in the keymap YAML file"

    layers = yaml_data.get("layers", {})
    combos = yaml_data.get("combos", [])

    output = StringIO()

    drawer = KeymapDrawer(
        config=config,
        out=output,
        layers=layers,
        layout=layout,
        combos=combos,
    )

    if layer_name:
        drawer.print_board(draw_layers=[layer_name])
    else:
        drawer.print_board()

    svg_content = output.getvalue()
    output.close()

    return svg_content


def live(args: Namespace, config: Config, scanner: "ScannerAPI | None" = None) -> None:
    """Show a live view of keypresses using GTK/WebKit."""
    # Customize layer label styling
    custom_draw_config = config.draw_config.model_copy(
        update={
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

    config = config.model_copy(update={"draw_config": custom_draw_config})

    # Load keymap data
    if hasattr(args, "keymap") and args.keymap:
        yaml_path = Path(args.keymap)
        if not yaml_path.exists():
            logger.error(f"Keymap YAML file not found at {yaml_path}")
            sys.exit(1)

        logger.info(f"Loading custom keymap from: {yaml_path.absolute()}")
        with open(yaml_path, "r", encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f)
    else:
        from zmk_buddy.data.keymaps import load_default_keymap

        logger.info("Loading default keymap (miryoku)")
        yaml_data = load_default_keymap()

    # Override layout with --zmk-keyboard if specified
    if hasattr(args, "zmk_keyboard") and args.zmk_keyboard:
        logger.info(f"Using ZMK keyboard layout: {args.zmk_keyboard}")
        keymap_layout = yaml_data.get("layout", {})
        yaml_data["layout"] = {
            "layout_name": keymap_layout.get("layout_name"),
            "zmk_keyboard": args.zmk_keyboard,
        }

    # Create and run the GTK application
    testing_mode = hasattr(args, "testing") and args.testing
    app = KeymapApp(yaml_data, config, testing_mode=testing_mode, zmk_scanner=scanner)

    logger.info("Starting GTK event loop...")
    exit_code = app.run([])
    sys.exit(exit_code)
