"""
ZMK Buddy - Live keymap visualization tool for ZMK keyboards.
Uses keymap-drawer for rendering keymaps.
"""

import logging
import sys
from argparse import ArgumentParser, Namespace

from keymap_drawer.config import Config

from zmk_buddy import logger
from zmk_buddy.live_preflight import has_pyqt6


def main() -> None:
    """Entry point for zmk-buddy - launches the live keymap viewer."""
    parser = ArgumentParser(
        description="ZMK Buddy - Live keymap visualization for ZMK keyboards"
    )
    _ = parser.add_argument(
        "-d", "--debug",
        action="store_true",
        help="Enable debug logging"
    )
    _ = parser.add_argument(
        "-k", "--keymap",
        type=str,
        metavar="<filename.yaml>",
        help=(
            "Path to a custom keymap YAML file "
            "(default: use built-in miryoku layout)"
        )
    )
    _ = parser.add_argument(
        "-t", "--testing",
        action="store_true",
        help="Testing mode: don't save stats, initialize all keys as learned (100 correct, 0 incorrect)"
    )
    args: Namespace = parser.parse_args()

    # Set log level based on debug flag
    if args.debug:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)

    # Check for PySide6 availability
    if not has_pyqt6():
        print("Error: PySide6 is not available.", file=sys.stderr)
        print("Please install zmk-buddy with all dependencies:", file=sys.stderr)
        print("  pip install zmk-buddy", file=sys.stderr)
        sys.exit(1)

    # Import and run live view
    from zmk_buddy.live import live

    config = Config()
    live(args, config)


if __name__ == "__main__":
    main()
