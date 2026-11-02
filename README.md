# macOS-macro
## macro.py - a tiny AutoHotkey-style macro recorder/player for macOS.

## Setup:
    pip3 install pynput

## Usage:
    python3 macro.py record my_macro.json          # F8 stops recording
    python3 macro.py play my_macro.json            # F10 aborts playback
    python3 macro.py play my_macro.json --loops 5 --speed 2.0
    python3 macro.py play my_macro.json --loops 0  # repeat until F10

## macOS permissions (System Settings > Privacy & Security), for the app you run this from (Terminal, iTerm, VS Code...):

    - Accessibility      (needed to SEND clicks/keys)
    - Input Monitoring   (needed to RECORD clicks/keys)
Restart the terminal app after granting them.
