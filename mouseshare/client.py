"""The client runs on the computer that borrows the other one's mouse and keyboard."""

import socket
import time

from . import clipboard
from .keymaps import swap_ctrl_cmd
from .protocol import MAX_CLIPBOARD, VERSION, Connection, auth_token

SERVER_TIMEOUT = 8.0
RETRY_DELAY = 2.0


class Client:
    def __init__(self, platform, host, port, password=None, swap="auto",
                 share_clipboard=True, scroll_speed=1.0, log=print):
        self.platform = platform
        self.host = host
        self.port = port
        self.password = password
        self.swap = swap
        self.share_clipboard = share_clipboard
        self.scroll_speed = scroll_speed
        self.log = log
        self.injector = platform.Injector()
        self._last_clip = None

    def run(self):
        waiting_logged = False
        while True:
            try:
                sock = socket.create_connection((self.host, self.port), timeout=5)
            except OSError as exc:
                if not waiting_logged:
                    self.log("Can't reach %s:%d (%s). Retrying every few seconds ..."
                             % (self.host, self.port, exc))
                    waiting_logged = True
                time.sleep(RETRY_DELAY)
                continue
            waiting_logged = False
            try:
                if self._session(sock) == "fatal":
                    return 1
            except (OSError, ValueError, ConnectionError):
                pass
            finally:
                self.injector.release_all()
            self.log("Disconnected from the server. Reconnecting ...")
            time.sleep(RETRY_DELAY)

    def _session(self, sock):
        sock.settimeout(SERVER_TIMEOUT)  # the server pings every 2s
        conn = Connection(sock)
        try:
            hello = conn.recv()
            if hello.get("t") != "hello" or hello.get("v") != VERSION:
                self.log("The server runs a different version; update both computers.")
                return "fatal"
            if hello.get("auth") and not self.password:
                self.log("The server requires a password. Start with --password.")
                return "fatal"
            nonce = hello.get("nonce", "")
            conn.send({
                "t": "hello", "v": VERSION, "os": self.platform.NAME,
                "name": socket.gethostname(),
                "screen": self.platform.screen_rect().as_list(),
                "auth": auth_token(self.password, nonce) if self.password else None,
            })
            swap = self.swap == "on" or (self.swap == "auto" and hello.get("os") != self.platform.NAME)
            self.log("Connected to %s (%s).%s" % (
                hello.get("name", "?"), hello.get("os", "?"),
                " Ctrl and Cmd are swapped so shortcuts feel native." if swap else ""))
            return self._loop(conn, swap)
        finally:
            conn.close()

    def _loop(self, conn, swap):
        inj = self.injector
        while True:
            msg = conn.recv()
            kind = msg.get("t")
            if kind == "m":
                inj.move(msg["x"], msg["y"])
            elif kind == "b":
                inj.button(msg["b"], msg["d"])
            elif kind == "s":
                inj.scroll(msg["dx"] * self.scroll_speed, msg["dy"] * self.scroll_speed)
            elif kind == "k":
                inj.key(swap_ctrl_cmd(msg["k"]) if swap else msg["k"], msg["d"])
            elif kind == "enter":
                inj.move(msg["x"], msg["y"])
            elif kind == "leave":
                inj.release_all()
                if self.share_clipboard:
                    self._push_clipboard(conn)
            elif kind == "clip":
                if self.share_clipboard and isinstance(msg.get("text"), str):
                    self._last_clip = msg["text"]
                    clipboard.set_text(msg["text"])
            elif kind == "ping":
                conn.send_async({"t": "pong"})
            elif kind == "error":
                self.log("Server refused the connection: %s" % msg.get("msg"))
                return "fatal"

    def _push_clipboard(self, conn):
        text = clipboard.get_text()
        if text and text != self._last_clip and len(text) <= MAX_CLIPBOARD:
            self._last_clip = text
            conn.send_async({"t": "clip", "text": text})
