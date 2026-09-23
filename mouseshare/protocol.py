"""Wire protocol: one JSON object per line over TCP.

Message types (field "t"):
  hello      handshake, both directions
  enter      server -> client: cursor arrived on the client screen
  leave      server -> client: cursor went back to the server
  m          server -> client: absolute cursor position {x, y}
  b          server -> client: mouse button {b: left|right|middle|x1|x2, d: pressed}
  s          server -> client: scroll in wheel notches {dx, dy}
  k          server -> client: key {k: name, d: pressed}
  clip       either way: clipboard text {text}
  ping/pong  keepalive
"""

import hashlib
import hmac
import json
import queue
import socket
import threading

VERSION = 1
DEFAULT_PORT = 24850
MAX_LINE = 4 * 1024 * 1024
MAX_CLIPBOARD = 1024 * 1024


def auth_token(password, nonce):
    return hmac.new(password.encode(), nonce.encode(), hashlib.sha256).hexdigest()


def check_token(password, nonce, token):
    return hmac.compare_digest(auth_token(password, nonce), str(token or ""))


class Connection:
    """A line-delimited JSON connection.

    `send_async` never blocks, so it is safe to call from OS input hooks, which
    get disabled by the OS if they take too long.
    """

    def __init__(self, sock):
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        self.sock = sock
        self._rfile = sock.makefile("rb")
        self._lock = threading.Lock()
        self._queue = queue.Queue()
        self.closed = threading.Event()
        threading.Thread(target=self._sender, daemon=True).start()

    def send(self, msg):
        data = (json.dumps(msg, separators=(",", ":")) + "\n").encode()
        with self._lock:
            self.sock.sendall(data)

    def send_async(self, msg):
        if not self.closed.is_set():
            self._queue.put(msg)

    def recv(self):
        line = self._rfile.readline(MAX_LINE)
        if not line:
            raise ConnectionError("connection closed")
        return json.loads(line)

    def _sender(self):
        while not self.closed.is_set():
            msg = self._queue.get()
            if msg is None:
                break
            try:
                self.send(msg)
            except OSError:
                self.close()

    def close(self):
        if self.closed.is_set():
            return
        self.closed.set()
        self._queue.put(None)
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()
