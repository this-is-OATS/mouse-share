"""The server runs on the computer the physical mouse and keyboard are plugged into."""

import secrets
import socket
import threading
import time

from . import clipboard
from .geometry import OPPOSITE, Rect, VirtualCursor, at_edge, edge_ratio, point_on_edge
from .protocol import MAX_CLIPBOARD, VERSION, Connection, check_token

PING_INTERVAL = 2.0
CLIENT_TIMEOUT = 6.0
REENTRY_COOLDOWN = 0.3
PANIC_MODIFIERS = ({"ctrl", "ctrl_r"}, {"alt", "alt_r"}, {"shift", "shift_r"})


class Server:
    def __init__(self, platform, side, port, password=None, share_clipboard=True, log=print):
        self.platform = platform
        self.side = side
        self.port = port
        self.password = password
        self.share_clipboard = share_clipboard
        self.log = log
        self.local_rect = platform.screen_rect()
        self.capture = platform.Capture(self)

        self._lock = threading.RLock()
        self._conn = None
        self._client_rect = None
        self._cursor = None
        self._held = set()
        self._cooldown_until = 0.0
        self._last_heard = 0.0
        self._last_clip = None

    # -- called from the OS input hooks; must stay fast ------------------------

    def local_move(self, x, y):
        if self._conn is None or time.monotonic() < self._cooldown_until:
            return
        if at_edge(self.local_rect, self.side, x, y):
            self._enter(edge_ratio(self.local_rect, self.side, x, y))

    def remote_move(self, dx, dy):
        with self._lock:
            if self._cursor is None:
                return
            if self._cursor.move(dx, dy):
                self._leave()
            else:
                self._send({"t": "m", "x": self._cursor.x, "y": self._cursor.y})

    def remote_button(self, name, pressed):
        self._send({"t": "b", "b": name, "d": pressed})

    def remote_scroll(self, dx, dy):
        self._send({"t": "s", "dx": dx, "dy": dy})

    def remote_key(self, name, pressed):
        if pressed:
            self._held.add(name)
        else:
            self._held.discard(name)
        if name == "esc" and pressed and all(self._held & group for group in PANIC_MODIFIERS):
            self.log("Ctrl+Alt+Shift+Esc pressed: taking the cursor back.")
            self.panic()
            return
        self._send({"t": "k", "k": name, "d": pressed})

    def panic(self):
        """Return control to this computer immediately, cursor in the middle."""
        with self._lock:
            if self.capture.remote:
                r = self.local_rect
                self._leave(point=(r.x + r.w // 2, r.y + r.h // 2))

    # -- switching screens -----------------------------------------------------

    def _enter(self, ratio):
        with self._lock:
            if self._conn is None or self.capture.remote:
                return
            self._cursor = VirtualCursor(self._client_rect, OPPOSITE[self.side], ratio)
            self._held.clear()
            self.capture.begin_remote()
            self._send({"t": "enter", "x": self._cursor.x, "y": self._cursor.y})
        if self.share_clipboard:
            threading.Thread(target=self._push_clipboard, daemon=True).start()

    def _leave(self, point=None):
        with self._lock:
            if not self.capture.remote:
                return
            if point is None:
                point = point_on_edge(self.local_rect, self.side, self._cursor.ratio(), inset=2)
            self._cursor = None
            self.capture.end_remote(*point)
            self._cooldown_until = time.monotonic() + REENTRY_COOLDOWN
            self._send({"t": "leave"})

    def _push_clipboard(self):
        text = clipboard.get_text()
        if text and text != self._last_clip and len(text) <= MAX_CLIPBOARD:
            self._last_clip = text
            self._send({"t": "clip", "text": text})

    def _send(self, msg):
        conn = self._conn
        if conn is not None:
            conn.send_async(msg)

    # -- networking ------------------------------------------------------------

    def run(self):
        self.capture.start()
        threading.Thread(target=self._heartbeat, daemon=True).start()
        listener = socket.create_server(("0.0.0.0", self.port))
        self.log("Waiting for the other computer to connect on port %d ..." % self.port)
        try:
            while True:
                sock, addr = listener.accept()
                threading.Thread(target=self._serve, args=(sock, addr), daemon=True).start()
        finally:
            self.panic()
            self.capture.stop()
            listener.close()

    def _serve(self, sock, addr):
        conn = Connection(sock)
        try:
            sock.settimeout(10)
            nonce = secrets.token_hex(16)
            conn.send({"t": "hello", "v": VERSION, "os": self.platform.NAME,
                       "name": socket.gethostname(), "nonce": nonce,
                       "auth": bool(self.password)})
            hello = conn.recv()
            if hello.get("t") != "hello" or hello.get("v") != VERSION:
                conn.send({"t": "error", "msg": "version mismatch; update both computers"})
                return
            if self.password and not check_token(self.password, nonce, hello.get("auth")):
                self.log("Rejected %s: wrong password." % addr[0])
                conn.send({"t": "error", "msg": "wrong password"})
                return
            sock.settimeout(None)
            self._attach(conn, hello, addr)
            while True:
                msg = conn.recv()
                self._last_heard = time.monotonic()
                if msg.get("t") == "clip" and isinstance(msg.get("text"), str):
                    self._last_clip = msg["text"]
                    clipboard.set_text(msg["text"])
        except (OSError, ValueError, ConnectionError):
            pass
        finally:
            self._detach(conn)
            conn.close()

    def _attach(self, conn, hello, addr):
        with self._lock:
            old = self._conn
            if old is not None:
                self._detach(old)
                old.close()
            self._client_rect = Rect.from_list(hello["screen"])
            self._last_heard = time.monotonic()
            self._conn = conn
        r = self._client_rect
        self.log("Connected to %s (%s) at %s, screen %dx%d. Move the mouse off the %s edge."
                 % (hello.get("name", "?"), hello.get("os", "?"), addr[0], r.w, r.h, self.side))

    def _detach(self, conn):
        with self._lock:
            if self._conn is not conn:
                return
            self.panic()
            self._conn = None
        self.log("Disconnected. Waiting for the other computer to reconnect ...")

    def _heartbeat(self):
        while True:
            time.sleep(PING_INTERVAL)
            conn = self._conn
            if conn is None:
                continue
            if time.monotonic() - self._last_heard > CLIENT_TIMEOUT:
                self.log("The other computer stopped responding.")
                conn.close()  # the reader thread notices and detaches
            else:
                conn.send_async({"t": "ping"})
