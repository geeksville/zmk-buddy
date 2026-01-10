# ZMK Buddy

A live keymap visualization tool for ZMK keyboards, built on top of [keymap-drawer](https://github.com/caksoylar/keymap-drawer).

## Features

- Live visualization of keyboard key presses
- Overlay display with configurable transparency
- Support for ZMK keymap YAML files
- Global keyboard monitoring (requires appropriate permissions)
- **Learning Mode**: Tracks your typing accuracy to help you learn touch typing

## Learning Mode

ZMK Buddy includes a learning feature to help you master touch typing without looking at the keyboard:

- **Accuracy Tracking**: Monitors each keypress and guesses at errors (i.e. it saw you press backspace after a key)
- **Progress Persistence**: Statistics are saved to your local data directory and persist between sessions
- **Visual Feedback**: Keys you've mastered are significantly dimmed, encouraging you to rely on muscle memory
- **Progress Summary**: Shows your overall learning progress at startup

### How It Works

1. Each time you type a key, it's tracked as "pending"
2. If you press another key (not backspace), the pending key is marked as **correct**
3. If you press backspace, the pending key is marked as **incorrect**
4. Once a key reaches 90% accuracy over at least 100 presses, it's considered "learned" and dimmed in the display

## Installation

```bash
pip install zmk-buddy
```

## Usage

```bash
zmk-buddy
```

By default, zmk-buddy looks for a keymap file at `test/miryoku.yaml`. 

### Options

- `-d, --debug`: Enable debug logging
- `-k, --keymap <file>`: Load a custom keymap YAML file

### Controls

- Press **y** to cycle through layers
- Press **x** to exit
- Drag the window to reposition it

## Requirements

- Python 3.12+
- PySide6 for the GUI

### Platform Support

ZMK Buddy supports global keyboard monitoring across all major platforms:

| Platform | Backend | Notes |
|----------|---------|-------|
| **Linux** | evdev (preferred) | Requires user to be in `input` group |
| **Windows** | pynput | Works out of the box |
| **macOS** | pynput | May require Accessibility permissions in System Preferences |

### Linux Permissions

For global keyboard monitoring on Linux, your user needs access to `/dev/input/event*` devices. Add your user to the `input` group:

```bash
sudo usermod -aG input $USER
```

Then log out and back in for the change to take effect.

## License

Copyright 2026 Kevin Hester, kevinh@geeksville.com
GPL V3 [license](LICENSE)