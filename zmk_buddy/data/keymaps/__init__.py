"""Keymap data and utilities for zmk-buddy."""

import yaml
from importlib.resources import files


def load_default_keymap() -> dict[str, object]:
    """Load the default miryoku keymap from package resources.
    
    Returns:
        dict: Parsed YAML keymap data
    """
    keymap_text = (
        files('zmk_buddy.data.keymaps')
        .joinpath('miryoku.yaml')
        .read_text(encoding='utf-8')
    )
    return yaml.safe_load(keymap_text)  # type: ignore[no-any-return]
