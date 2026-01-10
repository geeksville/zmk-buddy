"""Utility functions for ZMK Buddy."""

from pathlib import Path

from platformdirs import user_data_dir


def get_settings_dir() -> Path:
    """Get the platform-specific settings directory for ZMK Buddy.
    
    Uses platformdirs to determine the appropriate location:
    - Linux: ~/.local/share/zmk-buddy
    - macOS: ~/Library/Application Support/zmk-buddy
    - Windows: C:\\Users\\<user>\\AppData\\Local\\zmk-buddy
    
    Creates the directory if it doesn't exist.
    
    Returns:
        Path to the settings directory
    """
    settings_dir = Path(user_data_dir("zmk-buddy", appauthor=False))
    settings_dir.mkdir(parents=True, exist_ok=True)
    return settings_dir
