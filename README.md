# ZMK Buddy

A live keymap visualization tool for ZMK keyboards, built on top of [keymap-drawer](https://github.com/caksoylar/keymap-drawer).

## Features

- Live visualization of keyboard key presses
- Overlay display with configurable transparency
- Support for ZMK keymap YAML files
- Layer cycling (press 'y' to switch layers)
- Global keyboard monitoring (requires appropriate permissions)

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

MIT