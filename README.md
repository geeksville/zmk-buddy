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

- **Accuracy Tracking**: Monitors each keypress and detects errors when you press backspace to correct a mistake
- **Progress Persistence**: Statistics are saved to your local data directory and persist between sessions
- **Visual Feedback**: Keys you've mastered (90%+ accuracy over 100+ presses) are dimmed to 20% opacity, encouraging you to rely on muscle memory
- **Progress Summary**: Shows your overall learning progress at startup

### How It Works

1. Each time you type a key, it's tracked as "pending"
2. If you press another key (not backspace), the pending key is marked as **correct**
3. If you press backspace, the pending key is marked as **incorrect**
4. Once a key reaches 90% accuracy over at least 100 presses, it's considered "learned" and dimmed in the display

Statistics are stored in:
- **Linux**: `~/.local/share/zmk-buddy/key_stats.json`
- **macOS**: `~/Library/Application Support/zmk-buddy/key_stats.json`
- **Windows**: `C:\Users\<user>\AppData\Local\zmk-buddy\key_stats.json`

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
- Linux (uses evdev for global keyboard monitoring)
- PySide6 for the GUI

### Permissions

For global keyboard monitoring to work, your user needs access to `/dev/input/event*` devices. Add your user to the `input` group:

```bash
sudo usermod -aG input $USER
```

Then log out and back in for the change to take effect.

## License

Copyright 2026 Kevin Hester, kevinh@geeksville.com
GPL V3 [license](LICENSE)