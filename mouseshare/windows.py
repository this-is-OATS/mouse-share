"""Windows input capture (server side) and injection (client side)."""

import ctypes

from pynput import keyboard, mouse

from .geometry import Rect
from .keymaps import WIN_VK

NAME = "windows"

user32 = ctypes.windll.user32

WM_MOUSEMOVE = 0x0200
WM_MOUSEWHEEL = 0x020A
WM_MOUSEHWHEEL = 0x020E
_BUTTON_MSGS = {
    0x0201: ("left", True), 0x0202: ("left", False),
    0x0204: ("right", True), 0x0205: ("right", False),
    0x0207: ("middle", True), 0x0208: ("middle", False),
}
WM_XBUTTONDOWN, WM_XBUTTONUP = 0x020B, 0x020C
WM_KEYDOWN, WM_SYSKEYDOWN = 0x0100, 0x0104
WHEEL_DELTA = 120
LLMHF_INJECTED = 0x01
LLKHF_INJECTED = 0x10

SM_CXSCREEN, SM_CYSCREEN = 0, 1
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79


def setup():
    """Use real pixels everywhere; otherwise scaled displays report wrong coordinates."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor aware
    except (AttributeError, OSError):
        user32.SetProcessDPIAware()


def screen_rect():
    """Bounding box of all monitors (the Windows 'virtual screen')."""
    return Rect(
        user32.GetSystemMetrics(SM_XVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_CXVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_CYVIRTUALSCREEN),
    )


def check_permissions(role):
    return []


def _high_word(value):
    return ctypes.c_short((value >> 16) & 0xFFFF).value


class Capture:
    """Watches the local mouse and keyboard. While `remote` is set, every event
    is swallowed and handed to the server instead of reaching local apps.

    Remote motion works by parking the real cursor and blocking all moves:
    each blocked move reports where the cursor *would* have gone, so the
    distance from the parking spot is the mouse delta.
    """

    def __init__(self, handler):
        self.handler = handler
        self.remote = False
        self._park = (0, 0)
        self._mouse = mouse.Listener(win32_event_filter=self._mouse_event)
        self._keyboard = keyboard.Listener(win32_event_filter=self._key_event)

    def start(self):
        self._mouse.start()
        self._keyboard.start()
        self._mouse.wait()
        self._keyboard.wait()

    def stop(self):
        self._mouse.stop()
        self._keyboard.stop()

    def begin_remote(self):
        self.remote = True
        # Park in the middle of the primary monitor so moves never hit an edge
        self._park = (user32.GetSystemMetrics(SM_CXSCREEN) // 2,
                      user32.GetSystemMetrics(SM_CYSCREEN) // 2)
        user32.SetCursorPos(*self._park)

    def end_remote(self, x, y):
        self.remote = False
        user32.SetCursorPos(int(x), int(y))

    def _mouse_event(self, msg, data):
        injected = data.flags & LLMHF_INJECTED
        if not self.remote:
            if msg == WM_MOUSEMOVE and not injected:
                self.handler.local_move(data.pt.x, data.pt.y)
                if self.remote:
                    self._mouse.suppress_event()
            return True
        if injected:
            return True

        if msg == WM_MOUSEMOVE:
            dx, dy = data.pt.x - self._park[0], data.pt.y - self._park[1]
            if dx or dy:
                self.handler.remote_move(dx, dy)
        elif msg in _BUTTON_MSGS:
            self.handler.remote_button(*_BUTTON_MSGS[msg])
        elif msg in (WM_XBUTTONDOWN, WM_XBUTTONUP):
            name = "x1" if _high_word(data.mouseData) == 1 else "x2"
            self.handler.remote_button(name, msg == WM_XBUTTONDOWN)
        elif msg == WM_MOUSEWHEEL:
            self.handler.remote_scroll(0, _high_word(data.mouseData) / WHEEL_DELTA)
        elif msg == WM_MOUSEHWHEEL:
            self.handler.remote_scroll(_high_word(data.mouseData) / WHEEL_DELTA, 0)
        self._mouse.suppress_event()

    def _key_event(self, msg, data):
        if not self.remote or data.flags & LLKHF_INJECTED:
            return True
        name = WIN_VK.get(data.vkCode)
        if name:
            self.handler.remote_key(name, msg in (WM_KEYDOWN, WM_SYSKEYDOWN))
        self._keyboard.suppress_event()


class Injector:
    """Replays events received from the server on this PC."""

    def __init__(self):
        self._mouse = mouse.Controller()
        self._keyboard = keyboard.Controller()
        self._keys = set()
        self._buttons = set()

    def move(self, x, y):
        self._mouse.position = (x, y)

    def button(self, name, pressed):
        button = getattr(mouse.Button, name, None)
        if button is None:
            return
        if pressed:
            self._mouse.press(button)
            self._buttons.add(name)
        elif name in self._buttons:
            self._mouse.release(button)
            self._buttons.discard(name)

    def scroll(self, dx, dy):
        self._mouse.scroll(dx, dy)

    def key(self, name, pressed):
        key = _resolve_key(name)
        if key is None:
            return
        if pressed:
            self._keyboard.press(key)
            self._keys.add(name)
        else:
            self._keyboard.release(key)
            self._keys.discard(name)

    def release_all(self):
        for name in list(self._keys):
            self.key(name, False)
        for name in list(self._buttons):
            self.button(name, False)


def _resolve_key(name):
    if len(name) == 1:
        return keyboard.KeyCode.from_char(name)
    return getattr(keyboard.Key, name, None)
