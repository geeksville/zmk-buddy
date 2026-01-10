# Development Guide

## Building with Poetry

This project uses [Poetry](https://python-poetry.org/) for dependency management and packaging.

### Initial Setup

1. Install Poetry if you haven't already:
   ```bash
   curl -sSL https://install.python-poetry.org | python3 -
   ```

2. Install dependencies:
   ```bash
   poetry install
   ```

### Running the Application

Run directly with Poetry:
```bash
poetry run zmk-buddy
```

Or from within the Poetry shell:
```bash
zmk-buddy
```

### Development Dependencies

Install development dependencies:
```bash
poetry install --with dev
```

## Using Just Recipes

This project uses [just](https://github.com/casey/just) as a command runner. View available recipes:
```bash
just
```

### Switching Between keymap-drawer Versions

#### Use PyPI Release Version

Switch to the published PyPI version of keymap-drawer:
```bash
just keymap-use-release
```

This removes any local development version and installs the latest release from PyPI (>=0.22.1).

#### Use Local Development Version

Switch to a local editable version for development:
```bash
just keymap-use-dev
```

Use this when you need to modify keymap-drawer alongside zmk-buddy development.

# Implementation notes

Statistics are stored in:
- **Linux**: `~/.local/share/zmk-buddy/key_stats.json`
- **macOS**: `~/Library/Application Support/zmk-buddy/key_stats.json`
- **Windows**: `C:\Users\<user>\AppData\Local\zmk-buddy\key_stats.json`

