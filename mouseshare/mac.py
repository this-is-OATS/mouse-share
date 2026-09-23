"""macOS input capture (server side) and injection (client side)."""

import ctypes
import math
import time

import Quartz
from AppKit import NSEvent
from pynput import keyboard, mouse

from .geometry import Rect
from .keymaps import MAC_CAPS_LOCK, MAC_KEYCODES, MAC_MODIFIER_BITS

NAME = "mac"
PIXELS_PER_NOTCH = 40.0

_MOVE_TYPES = {
    Quartz.kCGEventMouseMoved,
    Quartz.kCGEventLeftMouseDragged,
    Quartz.kCGEventRightMouseDragged,
    Quartz.kCGEventOtherMouseDragged,
}
_DOWN_TYPES = {
    Quartz.kCGEventLeftMouseDown: "left",
    Quartz.kCGEventRightMouseDown: "right",
    Quartz.kCGEventOtherMouseDown: None,
}
_UP_TYPES = {
    Quartz.kCGEventLeftMouseUp: "left",
    Quartz.kCGEventRightMouseUp: "right",
    Quartz.kCGEventOtherMouseUp: None,
}
_OTHER_BUTTONS = {2: "middle", 3: "x1", 4: "x2"}
_TAP_DISABLED = {Quartz.kCGEventTapDisabledByTimeout, Quartz.kCGEventTapDisabledByUserInput}

# name -> (down type, up type, dragged type, CG button number)
_BUTTONS = {
    "left": (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp,
             Quartz.kCGEventLeftMouseDragged, Quartz.kCGMouseButtonLeft),
    "right": (Quartz.kCGEventRightMouseDown, Quartz.kCGEventRightMouseUp,
              Quartz.kCGEventRightMouseDragged, Quartz.kCGMouseButtonRight),
}
for _number, _name in _OTHER_BUTTONS.items():
    _BUTTONS[_name] = (Quartz.kCGEventOtherMouseDown, Quartz.kCGEventOtherMouseUp,
                       Quartz.kCGEventOtherMouseDragged, _number)


def setup():
    pass


def screen_rect():
    """Bounding box of all displays, in the global coordinates events use."""
    _, displays, count = Quartz.CGGetActiveDisplayList(16, None, None)
    bounds = [Quartz.CGDisplayBounds(d) for d in displays[:count]]
    x1 = min(b.origin.x for b in bounds)
    y1 = min(b.origin.y for b in bounds)
    x2 = max(b.origin.x + b.size.width for b in bounds)
    y2 = max(b.origin.y + b.size.height for b in bounds)
    return Rect(int(x1), int(y1), int(x2 - x1), int(y2 - y1))


def check_permissions(role):
    """Return a list of human-readable problems, empty if everything is granted."""
    from ApplicationServices import AXIsProcessTrusted

    problems = []
    if not AXIsProcessTrusted():
        problems.append("Accessibility")
    if role == "server" and hasattr(Quartz, "CGPreflightListenEventAccess"):
        if not Quartz.CGPreflightListenEventAccess():
            Quartz.CGRequestListenEventAccess()
            problems.append("Input Monitoring")
    if problems:
        return [
            "macOS needs %s permission for the app running this (Terminal, iTerm, "
            "or Python). Open System Settings > Privacy & Security > %s, turn it "
            "on, then restart this program." % (" and ".join(problems), " / ".join(problems))
        ]
    return []


def _allow_background_cursor_hide():
    """Let a background process hide the cursor (same trick Barrier/Synergy use)."""
    try:
        cg = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        cf = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        cg._CGSDefaultConnection.restype = ctypes.c_int
        cf.CFStringCreateWithCString.restype = ctypes.c_void_p
        cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
        cg.CGSSetConnectionProperty.argtypes = [
            ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p]
        conn = cg._CGSDefaultConnection()
        key = cf.CFStringCreateWithCString(None, b"SetsCursorInBackground", 0x08000100)
        true = ctypes.c_void_p.in_dll(cf, "kCFBooleanTrue")
        cg.CGSSetConnectionProperty(conn, conn, key, true)
        return True
    except (OSError, AttributeError, ValueError):
        return False


class Capture:
    """Watches the local mouse and keyboard. While `remote` is set, every event
    is swallowed and handed to the server instead of reaching local apps."""

    def __init__(self, handler):
        self.handler = handler
        self.remote = False
        self._hidden = False
        self._can_hide = _allow_background_cursor_hide()
        self._mouse = mouse.Listener(darwin_intercept=self._mouse_event)
        self._keyboard = keyboard.Listener(darwin_intercept=self._key_event)

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
        # Freeze the pointer; mouse events still arrive and carry raw deltas
        Quartz.CGAssociateMouseAndMouseCursorPosition(False)
        if self._can_hide and not self._hidden:
            Quartz.CGDisplayHideCursor(Quartz.CGMainDisplayID())
            self._hidden = True

    def end_remote(self, x, y):
        self.remote = False
        Quartz.CGWarpMouseCursorPosition((x, y))
        # Re-associating right after a warp also cancels the warp's input freeze
        Quartz.CGAssociateMouseAndMouseCursorPosition(True)
        if self._hidden:
            Quartz.CGDisplayShowCursor(Quartz.CGMainDisplayID())
            self._hidden = False

    def _mouse_event(self, etype, event):
        if etype in _TAP_DISABLED:
            # The OS turned our hook off; give the user their cursor back
            self.handler.panic()
            return event
        if not self.remote:
            if etype in _MOVE_TYPES:
                loc = Quartz.CGEventGetLocation(event)
                self.handler.local_move(loc.x, loc.y)
                if self.remote:
                    return None
            return event

        field = Quartz.CGEventGetIntegerValueField
        if etype in _MOVE_TYPES:
            dx = field(event, Quartz.kCGMouseEventDeltaX)
            dy = field(event, Quartz.kCGMouseEventDeltaY)
            if dx or dy:
                self.handler.remote_move(dx, dy)
        elif etype in _DOWN_TYPES or etype in _UP_TYPES:
            name = _DOWN_TYPES.get(etype) or _UP_TYPES.get(etype)
            if name is None:
                name = _OTHER_BUTTONS.get(field(event, Quartz.kCGMouseEventButtonNumber))
            if name:
                self.handler.remote_button(name, etype in _DOWN_TYPES)
        elif etype == Quartz.kCGEventScrollWheel:
            if field(event, Quartz.kCGScrollWheelEventIsContinuous):
                dy = field(event, Quartz.kCGScrollWheelEventPointDeltaAxis1) / PIXELS_PER_NOTCH
                dx = field(event, Quartz.kCGScrollWheelEventPointDeltaAxis2) / PIXELS_PER_NOTCH
            else:
                dy = field(event, Quartz.kCGScrollWheelEventDeltaAxis1)
                dx = field(event, Quartz.kCGScrollWheelEventDeltaAxis2)
            if dx or dy:
                # macOS horizontal axis is positive-left; the protocol is positive-right
                self.handler.remote_scroll(-dx, dy)
        return None

    def _key_event(self, etype, event):
        if etype in _TAP_DISABLED:
            self.handler.panic()
            return event
        if not self.remote:
            return event
        code = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
        if etype in (Quartz.kCGEventKeyDown, Quartz.kCGEventKeyUp):
            name = MAC_KEYCODES.get(code)
            if name:
                self.handler.remote_key(name, etype == Quartz.kCGEventKeyDown)
        elif etype == Quartz.kCGEventFlagsChanged:
            if code == MAC_CAPS_LOCK:
                # macOS reports caps lock as a toggle, not as down/up
                self.handler.remote_key("caps_lock", True)
                self.handler.remote_key("caps_lock", False)
            elif code in MAC_MODIFIER_BITS:
                pressed = bool(Quartz.CGEventGetFlags(event) & MAC_MODIFIER_BITS[code])
                self.handler.remote_key(MAC_KEYCODES[code], pressed)
        return None


class Injector:
    """Replays events received from the server on this Mac."""

    def __init__(self):
        self._keyboard = keyboard.Controller()
        self._keys = set()
        self._buttons = []
        self._pos = self._current_pos()
        self._last_press = (None, 0.0, (0, 0))
        self._clicks = 0
        self._scroll_rest = [0.0, 0.0]

    @staticmethod
    def _current_pos():
        loc = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
        return (loc.x, loc.y)

    @staticmethod
    def _post(event):
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)

    def move(self, x, y):
        self._pos = (x, y)
        if self._buttons:
            _, _, etype, number = _BUTTONS[self._buttons[-1]]
        else:
            etype, number = Quartz.kCGEventMouseMoved, 0
        self._post(Quartz.CGEventCreateMouseEvent(None, etype, self._pos, number))

    def button(self, name, pressed):
        if name not in _BUTTONS:
            return
        down, up, _, number = _BUTTONS[name]
        if pressed:
            # macOS apps only see a double-click if we count clicks ourselves
            last_name, last_time, last_pos = self._last_press
            now = time.monotonic()
            close = math.dist(last_pos, self._pos) <= 4
            if name == last_name and close and now - last_time <= NSEvent.doubleClickInterval():
                self._clicks += 1
            else:
                self._clicks = 1
            self._last_press = (name, now, self._pos)
            if name not in self._buttons:
                self._buttons.append(name)
        elif name in self._buttons:
            self._buttons.remove(name)
        else:
            return
        event = Quartz.CGEventCreateMouseEvent(None, down if pressed else up, self._pos, number)
        Quartz.CGEventSetIntegerValueField(event, Quartz.kCGMouseEventClickState, self._clicks)
        self._post(event)

    def scroll(self, dx, dy):
        self._scroll_rest[0] += dx * PIXELS_PER_NOTCH
        self._scroll_rest[1] += dy * PIXELS_PER_NOTCH
        px, py = int(self._scroll_rest[0]), int(self._scroll_rest[1])
        if px or py:
            self._scroll_rest[0] -= px
            self._scroll_rest[1] -= py
            self._post(Quartz.CGEventCreateScrollWheelEvent(
                None, Quartz.kCGScrollEventUnitPixel, 2, py, -px))

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


# PC keys a Mac keyboard doesn't have -> what Mac keyboards put in that spot
_PC_ONLY_KEYS = {
    "print_screen": keyboard.Key.f13,
    "scroll_lock": keyboard.Key.f14,
    "pause": keyboard.Key.f15,
    "insert": keyboard.KeyCode.from_vk(114),  # Help
}


def _resolve_key(name):
    if len(name) == 1:
        return keyboard.KeyCode.from_char(name)
    return getattr(keyboard.Key, name, None) or _PC_ONLY_KEYS.get(name)
