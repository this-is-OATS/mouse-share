import socket
import threading
import time
import types
import unittest

from mouseshare import keymaps
from mouseshare.client import Client
from mouseshare.geometry import Rect, VirtualCursor, at_edge, edge_ratio, point_on_edge
from mouseshare.protocol import auth_token, check_token
from mouseshare.server import Server


class GeometryTest(unittest.TestCase):
    def test_edges(self):
        r = Rect(0, 0, 1920, 1080)
        self.assertTrue(at_edge(r, "right", 1919, 500))
        self.assertFalse(at_edge(r, "right", 1918, 500))
        self.assertTrue(at_edge(r, "left", 0, 500))
        self.assertTrue(at_edge(r, "top", 10, 0))
        self.assertTrue(at_edge(r, "bottom", 10, 1079))

    def test_ratio_maps_between_different_sizes(self):
        server = Rect(0, 0, 1920, 1080)
        client = Rect(0, 0, 1440, 900)
        ratio = edge_ratio(server, "right", 1919, 1079)
        self.assertEqual(point_on_edge(client, "left", ratio, inset=1), (1, 899))

    def test_negative_origin_monitor(self):
        r = Rect(-1920, 0, 3840, 1080)
        self.assertTrue(at_edge(r, "left", -1920, 5))
        self.assertEqual(point_on_edge(r, "left", 0.0, inset=2), (-1918, 0))

    def test_virtual_cursor_exits_only_through_return_side(self):
        cursor = VirtualCursor(Rect(0, 0, 1000, 800), "left", 0.5)
        self.assertEqual((cursor.x, cursor.y), (1, 400))
        self.assertFalse(cursor.move(5000, 0))   # clamps at far edge, stays
        self.assertEqual(cursor.x, 999)
        self.assertFalse(cursor.move(0, -5000))  # clamps at top, stays
        self.assertEqual(cursor.y, 0)
        self.assertFalse(cursor.move(-999, 0))
        self.assertTrue(cursor.move(-1, 0))      # past the left edge -> back to server


class KeymapTest(unittest.TestCase):
    def test_tables_agree_on_names(self):
        mac, win = set(keymaps.MAC_KEYCODES.values()), set(keymaps.WIN_VK.values())
        for name in "abcxyz0189;',./[]\\`-=":
            self.assertIn(name, mac)
            self.assertIn(name, win)
        for name in ("enter", "esc", "tab", "space", "backspace", "shift", "ctrl", "alt",
                     "cmd", "left", "up", "f1", "f12", "delete", "home", "page_down"):
            self.assertIn(name, mac)
            self.assertIn(name, win)

    def test_names_are_valid_pynput_keys(self):
        from pynput.keyboard._base import Key  # the names every platform understands

        for name in set(keymaps.MAC_KEYCODES.values()) | set(keymaps.WIN_VK.values()):
            if len(name) > 1:
                self.assertIn(name, Key.__members__, name)

    def test_modifier_bits_cover_modifiers(self):
        for code in keymaps.MAC_MODIFIER_BITS:
            self.assertIn(keymaps.MAC_KEYCODES[code], {
                "cmd", "cmd_r", "shift", "shift_r", "ctrl", "ctrl_r", "alt", "alt_r"})

    def test_swap(self):
        self.assertEqual(keymaps.swap_ctrl_cmd("ctrl"), "cmd")
        self.assertEqual(keymaps.swap_ctrl_cmd("cmd_r"), "ctrl_r")
        self.assertEqual(keymaps.swap_ctrl_cmd("a"), "a")


class AuthTest(unittest.TestCase):
    def test_token(self):
        token = auth_token("hunter2", "abc")
        self.assertTrue(check_token("hunter2", "abc", token))
        self.assertFalse(check_token("wrong", "abc", token))
        self.assertFalse(check_token("hunter2", "abc", None))


class FakeCapture:
    def __init__(self, handler):
        self.handler = handler
        self.remote = False
        self.returned_to = None

    def start(self):
        pass

    def stop(self):
        pass

    def begin_remote(self):
        self.remote = True

    def end_remote(self, x, y):
        self.remote = False
        self.returned_to = (x, y)


class FakeInjector:
    def __init__(self):
        self.events = []

    def move(self, x, y):
        self.events.append(("move", x, y))

    def button(self, name, pressed):
        self.events.append(("button", name, pressed))

    def scroll(self, dx, dy):
        self.events.append(("scroll", dx, dy))

    def key(self, name, pressed):
        self.events.append(("key", name, pressed))

    def release_all(self):
        self.events.append(("release_all",))


def fake_platform(name, rect):
    return types.SimpleNamespace(NAME=name, screen_rect=lambda: rect,
                                 Capture=FakeCapture, Injector=FakeInjector)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class EndToEndTest(unittest.TestCase):
    """A real server and client talking over loopback, with fake OS hooks."""

    def start(self, server_password="pw", client_password="pw"):
        port = free_port()
        self.logs = []
        self.server = Server(fake_platform("windows", Rect(0, 0, 1920, 1080)), "right", port,
                             server_password, share_clipboard=False, log=self.logs.append)
        self.client = Client(fake_platform("mac", Rect(0, 0, 1440, 900)), "127.0.0.1", port,
                             client_password, share_clipboard=False, log=self.logs.append)
        threading.Thread(target=self.server.run, daemon=True).start()
        self.client_result = []
        threading.Thread(target=lambda: self.client_result.append(self.client.run()),
                         daemon=True).start()

    def test_full_round_trip(self):
        self.start()
        self.assertTrue(wait_for(lambda: self.server._conn is not None), self.logs)
        events = self.client.injector.events

        self.server.local_move(1000, 540)           # not at the edge: nothing happens
        self.assertFalse(self.server.capture.remote)

        self.server.local_move(1919, 540)           # hit the right edge
        self.assertTrue(self.server.capture.remote)
        self.server.remote_move(100, 0)
        self.server.remote_button("left", True)
        self.server.remote_button("left", False)
        self.server.remote_scroll(0, -1.0)
        self.server.remote_key("ctrl", True)        # PC ctrl becomes Mac cmd
        self.server.remote_key("c", True)
        self.server.remote_key("c", False)
        self.server.remote_key("ctrl", False)
        self.server.remote_move(-500, 0)            # back across the left edge of the Mac

        self.assertTrue(wait_for(lambda: ("release_all",) in events), events)
        self.assertFalse(self.server.capture.remote)
        y = round(540 / 1079 * 899)
        self.assertEqual(events[:9], [
            ("move", 1, y),
            ("move", 101, y),
            ("button", "left", True),
            ("button", "left", False),
            ("scroll", 0.0, -1.0),
            ("key", "cmd", True),
            ("key", "c", True),
            ("key", "c", False),
            ("key", "cmd", False),
        ])
        # Came back on the server's right edge at the same height, 2px inside
        self.assertEqual(self.server.capture.returned_to, (1917, 540))

        # Cooldown stops an instant bounce back, then crossing works again
        self.server.local_move(1919, 540)
        self.assertFalse(self.server.capture.remote)
        time.sleep(0.35)
        self.server.local_move(1919, 540)
        self.assertTrue(self.server.capture.remote)

    def test_panic_hotkey_returns_control(self):
        self.start()
        self.assertTrue(wait_for(lambda: self.server._conn is not None))
        self.server.local_move(1919, 10)
        for key in ("ctrl", "alt_r", "shift"):
            self.server.remote_key(key, True)
        self.server.remote_key("esc", True)
        self.assertFalse(self.server.capture.remote)
        self.assertEqual(self.server.capture.returned_to, (960, 540))

    def test_wrong_password_is_rejected(self):
        self.start(client_password="nope")
        self.assertTrue(wait_for(lambda: self.client_result == [1]), self.logs)
        self.assertIsNone(self.server._conn)
        self.assertTrue(any("wrong password" in line for line in self.logs), self.logs)

    def test_disconnect_while_remote_gives_cursor_back(self):
        self.start()
        self.assertTrue(wait_for(lambda: self.server._conn is not None))
        self.server.local_move(1919, 540)
        self.assertTrue(self.server.capture.remote)
        self.server._conn.close()
        self.assertTrue(wait_for(lambda: not self.server.capture.remote))


if __name__ == "__main__":
    unittest.main()
