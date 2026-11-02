#!/usr/bin/env python3

import argparse
import json
import sys
import threading
import time

from pynput import keyboard, mouse

STOP_RECORD_KEY = keyboard.Key.f8
ABORT_PLAY_KEY = keyboard.Key.f10
MOVE_INTERVAL = 0.03  # seconds between recorded mouse-move samples


# ----------------------------------------------------------------------------
# Key encoding / decoding
# ----------------------------------------------------------------------------
def encode_key(key):
    """Turn a pynput key into a JSON-friendly dict."""
    if isinstance(key, keyboard.Key):  # special keys: enter, shift, cmd, f1...
        return {"kind": "special", "name": key.name}
    # Prefer the virtual key code: it is layout-independent and replays
    # correctly even when modifiers (cmd/ctrl) were held while recording.
    if getattr(key, "vk", None) is not None:
        return {"kind": "vk", "value": key.vk}
    return {"kind": "char", "value": key.char}


def decode_key(data):
    if data["kind"] == "special":
        return keyboard.Key[data["name"]]
    if data["kind"] == "vk":
        return keyboard.KeyCode.from_vk(data["value"])
    return keyboard.KeyCode.from_char(data["value"])


# ----------------------------------------------------------------------------
# Recording
# ----------------------------------------------------------------------------
def record(path, capture_moves=True, countdown=3):
    events = []
    lock = threading.Lock()
    state = {"last_move": 0.0}

    print(f"Recording starts in {countdown}s. Switch to your target window.")
    for i in range(countdown, 0, -1):
        print(f"  {i}...")
        time.sleep(1)
    print("Recording! Press F8 to stop.")

    start = time.perf_counter()

    def add(event):
        event["t"] = time.perf_counter() - start
        with lock:
            events.append(event)

    # --- mouse callbacks ---
    def on_move(x, y):
        if not capture_moves:
            return
        now = time.perf_counter()
        if now - state["last_move"] >= MOVE_INTERVAL:
            state["last_move"] = now
            add({"type": "move", "x": x, "y": y})

    def on_click(x, y, button, pressed):
        add({"type": "click", "x": x, "y": y,
             "button": button.name, "pressed": pressed})

    def on_scroll(x, y, dx, dy):
        add({"type": "scroll", "x": x, "y": y, "dx": dx, "dy": dy})

    # --- keyboard callbacks ---
    def on_press(key):
        if key == STOP_RECORD_KEY:
            return False  # stops the keyboard listener
        add({"type": "key", "pressed": True, "key": encode_key(key)})

    def on_release(key):
        if key == STOP_RECORD_KEY:
            return
        add({"type": "key", "pressed": False, "key": encode_key(key)})

    mouse_listener = mouse.Listener(
        on_move=on_move, on_click=on_click, on_scroll=on_scroll)
    key_listener = keyboard.Listener(on_press=on_press, on_release=on_release)

    mouse_listener.start()
    key_listener.start()
    key_listener.join()      # blocks until F8
    mouse_listener.stop()

    if not events:
        print("No events recorded.")
        return

    # Trim the idle time before the first action.
    offset = events[0]["t"]
    for e in events:
        e["t"] = round(e["t"] - offset, 4)

    with open(path, "w") as f:
        json.dump(events, f, indent=1)
    print(f"Saved {len(events)} events to {path}")


# ----------------------------------------------------------------------------
# Playback
# ----------------------------------------------------------------------------
def play(path, loops=1, speed=1.0, start_delay=3):
    with open(path) as f:
        events = json.load(f)
    if not events:
        print("Macro is empty.")
        return

    mouse_ctl = mouse.Controller()
    key_ctl = keyboard.Controller()
    abort = threading.Event()

    held_keys = []
    held_buttons = []

    def on_press(key):
        if key == ABORT_PLAY_KEY:
            abort.set()
            return False

    abort_listener = keyboard.Listener(on_press=on_press)
    abort_listener.start()

    def release_everything():
        """Don't leave modifiers or mouse buttons stuck down."""
        for k in held_keys:
            try:
                key_ctl.release(k)
            except Exception:
                pass
        for b in held_buttons:
            try:
                mouse_ctl.release(b)
            except Exception:
                pass
        held_keys.clear()
        held_buttons.clear()

    def apply(e):
        kind = e["type"]
        if kind == "move":
            mouse_ctl.position = (e["x"], e["y"])
        elif kind == "click":
            mouse_ctl.position = (e["x"], e["y"])
            button = mouse.Button[e["button"]]
            if e["pressed"]:
                mouse_ctl.press(button)
                held_buttons.append(button)
            else:
                mouse_ctl.release(button)
                if button in held_buttons:
                    held_buttons.remove(button)
        elif kind == "scroll":
            mouse_ctl.position = (e["x"], e["y"])
            mouse_ctl.scroll(e["dx"], e["dy"])
        elif kind == "key":
            key = decode_key(e["key"])
            if e["pressed"]:
                key_ctl.press(key)
                held_keys.append(key)
            else:
                key_ctl.release(key)
                if key in held_keys:
                    held_keys.remove(key)

    print(f"Playback starts in {start_delay}s. Press F10 to abort.")
    if abort.wait(start_delay):
        return

    run = 0
    try:
        while not abort.is_set() and (loops == 0 or run < loops):
            run += 1
            print(f"Run {run}" + (f"/{loops}" if loops else ""))
            t_start = time.perf_counter()
            for e in events:
                target = t_start + e["t"] / speed
                delay = target - time.perf_counter()
                if delay > 0 and abort.wait(delay):
                    break
                if abort.is_set():
                    break
                apply(e)
            if loops == 0 or run < loops:
                abort.wait(0.2)  # small gap between loops
    finally:
        release_everything()
        abort_listener.stop()

    print("Aborted." if abort.is_set() else "Done.")


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Simple macOS macro recorder")
    sub = parser.add_subparsers(dest="cmd", required=True)

    rec = sub.add_parser("record", help="record a macro (F8 to stop)")
    rec.add_argument("file")
    rec.add_argument("--no-moves", action="store_true",
                     help="only record clicks/scrolls/keys, not mouse movement")
    rec.add_argument("--countdown", type=int, default=3)

    pl = sub.add_parser("play", help="play a macro (F10 to abort)")
    pl.add_argument("file")
    pl.add_argument("--loops", type=int, default=1,
                    help="number of repeats, 0 = until aborted")
    pl.add_argument("--speed", type=float, default=1.0,
                    help="2.0 = twice as fast, 0.5 = half speed")
    pl.add_argument("--start-delay", type=int, default=3)

    args = parser.parse_args()
    try:
        if args.cmd == "record":
            record(args.file, not args.no_moves, args.countdown)
        else:
            play(args.file, args.loops, args.speed, args.start_delay)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(1)


if __name__ == "__main__":
    main()