"""
ZMK Buddy - Live keymap visualization tool for ZMK keyboards.
Uses keymap-drawer for rendering keymaps.
"""

import logging
import sys
from argparse import ArgumentParser, FileType, Namespace

import yaml

from keymap_drawer.config import Config

from zmk_buddy import logger
from zmk_buddy.live_preflight import has_gtk
from zmk_buddy.zmk_client import ScannerAPI, SimScanner, ZMKScanner


def main() -> None:
    """Entry point for zmk-buddy - launches the live keymap viewer."""
    parser = ArgumentParser(description="ZMK Buddy - Live keymap visualization for ZMK keyboards")
    _ = parser.add_argument("-d", "--debug", action="store_true", help="Enable debug logging")
    _ = parser.add_argument(
        "-c",
        "--config",
        help="A YAML file containing settings for parsing and drawing, "
        "default can be dumped using the `keymap dump-config` command and modified",
        type=FileType("rt", encoding="utf-8"),
    )
    _ = parser.add_argument(
        "-z",
        "--zmk-keyboard",
        help="Name of the keyboard in ZMK, to look up physical layout for",
    )
    _ = parser.add_argument(
        "-k",
        "--keymap",
        type=str,
        metavar="<filename.yaml>",
        help=("Path to a custom keymap YAML file " "(default: use built-in miryoku layout)"),
    )
    _ = parser.add_argument(
        "-t",
        "--testing",
        action="store_true",
        help="Testing mode: don't save stats, initialize all keys as learned (100 correct, 0 incorrect)",
    )
    args: Namespace = parser.parse_args()

    # Set log level based on debug flag
    if args.debug:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)

    # Check for GTK availability
    if not has_gtk():
        print("Error: PyGObject/GTK4 is not available.", file=sys.stderr)
        print("Please install zmk-buddy with all dependencies:", file=sys.stderr)
        print("  pip install zmk-buddy", file=sys.stderr)
        sys.exit(1)

    # Import and run live view
    from zmk_buddy.live_gtk import live

    # Load config from file if specified, otherwise use defaults
    config = Config.model_validate(yaml.safe_load(args.config)) if args.config else Config()

    # Create scanner - use SimScanner in testing mode, ZMKScanner otherwise
    testing_mode = args.testing
    scanner: ScannerAPI
    if testing_mode:
        logger.info("Testing mode: using simulated ZMK scanner")
        scanner = SimScanner()
    else:
        scanner = ZMKScanner()

    try:
        # Run the GTK application (this will handle starting/stopping the scanner)
        live(args, config, scanner)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        # Ensure scanner is stopped on exit
        logger.info("Cleaning up...")


if __name__ == "__main__":
    main()
