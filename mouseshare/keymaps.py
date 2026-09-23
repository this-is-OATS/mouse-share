"""Translate each OS's raw key codes to shared key names, and back.

Names are pynput `Key` member names ("enter", "cmd_r", "f5", ...) for special
keys, or a single unshifted US-layout character ("a", "1", ";") for everything
else. Shift is sent as its own key, so "!" travels as shift + "1".
"""

# macOS virtual key codes (ANSI layout) -> name
MAC_KEYCODES = {
    0: "a", 1: "s", 2: "d", 3: "f", 4: "h", 5: "g", 6: "z", 7: "x", 8: "c", 9: "v",
    10: "`", 11: "b", 12: "q", 13: "w", 14: "e", 15: "r", 16: "y", 17: "t",
    18: "1", 19: "2", 20: "3", 21: "4", 22: "6", 23: "5", 24: "=", 25: "9",
    26: "7", 27: "-", 28: "8", 29: "0", 30: "]", 31: "o", 32: "u", 33: "[",
    34: "i", 35: "p", 36: "enter", 37: "l", 38: "j", 39: "'", 40: "k", 41: ";",
    42: "\\", 43: ",", 44: "/", 45: "n", 46: "m", 47: ".", 48: "tab",
    49: "space", 50: "`", 51: "backspace", 53: "esc",
    54: "cmd_r", 55: "cmd", 56: "shift", 57: "caps_lock", 58: "alt", 59: "ctrl",
    60: "shift_r", 61: "alt_r", 62: "ctrl_r",
    # Keypad: sent as the plain characters
    65: ".", 67: "*", 69: "+", 71: "num_lock", 75: "/", 76: "enter", 78: "-",
    81: "=", 82: "0", 83: "1", 84: "2", 85: "3", 86: "4", 87: "5", 88: "6",
    89: "7", 91: "8", 92: "9",
    96: "f5", 97: "f6", 98: "f7", 99: "f3", 100: "f8", 101: "f9", 103: "f11",
    105: "f13", 106: "f16", 107: "f14", 109: "f10", 111: "f12", 113: "f15",
    64: "f17", 79: "f18", 80: "f19", 90: "f20",
    114: "insert", 115: "home", 116: "page_up", 117: "delete", 118: "f4",
    119: "end", 120: "f2", 121: "page_down", 122: "f1",
    123: "left", 124: "right", 125: "down", 126: "up",
}

# macOS FlagsChanged: device-dependent bit that is set while that exact key is down
MAC_MODIFIER_BITS = {
    55: 0x08,     # left cmd
    54: 0x10,     # right cmd
    56: 0x02,     # left shift
    60: 0x04,     # right shift
    59: 0x01,     # left ctrl
    62: 0x2000,   # right ctrl
    58: 0x20,     # left option
    61: 0x40,     # right option
}
MAC_CAPS_LOCK = 57

# Windows virtual-key codes -> name
WIN_VK = {
    0x08: "backspace", 0x09: "tab", 0x0D: "enter", 0x10: "shift", 0x11: "ctrl",
    0x12: "alt", 0x13: "pause", 0x14: "caps_lock", 0x1B: "esc", 0x20: "space",
    0x21: "page_up", 0x22: "page_down", 0x23: "end", 0x24: "home",
    0x25: "left", 0x26: "up", 0x27: "right", 0x28: "down",
    0x2C: "print_screen", 0x2D: "insert", 0x2E: "delete",
    0x5B: "cmd", 0x5C: "cmd_r", 0x5D: "menu",
    0x6A: "*", 0x6B: "+", 0x6D: "-", 0x6E: ".", 0x6F: "/",
    0x90: "num_lock", 0x91: "scroll_lock",
    0xA0: "shift", 0xA1: "shift_r", 0xA2: "ctrl", 0xA3: "ctrl_r",
    0xA4: "alt", 0xA5: "alt_r",
    0xAD: "media_volume_mute", 0xAE: "media_volume_down", 0xAF: "media_volume_up",
    0xB0: "media_next", 0xB1: "media_previous", 0xB3: "media_play_pause",
    0xBA: ";", 0xBB: "=", 0xBC: ",", 0xBD: "-", 0xBE: ".", 0xBF: "/", 0xC0: "`",
    0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'",
}
WIN_VK.update({0x30 + i: str(i) for i in range(10)})           # 0-9
WIN_VK.update({0x41 + i: chr(ord("a") + i) for i in range(26)})  # A-Z
WIN_VK.update({0x60 + i: str(i) for i in range(10)})           # keypad 0-9
WIN_VK.update({0x70 + i: "f%d" % (i + 1) for i in range(20)})  # F1-F20

# Ctrl <-> Cmd, so the shortcut keys you are used to keep working across OSes
_SWAP = {"ctrl": "cmd", "ctrl_l": "cmd_l", "ctrl_r": "cmd_r"}
_SWAP.update({v: k for k, v in _SWAP.items()})


def swap_ctrl_cmd(name):
    return _SWAP.get(name, name)
