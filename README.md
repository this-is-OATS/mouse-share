# mouseshare

Use one mouse and keyboard across a Mac and a Windows PC. Push the cursor off
the edge of one screen and it shows up on the other; the keyboard follows it.
Copied text syncs between the two when you cross over.

- **Server**: the computer the mouse and keyboard are plugged into.
- **Client**: the other computer.

Either one can be the Mac. Both must be on the same network.

## Setup (on both computers)

1. Install Python 3.9+ ([python.org](https://www.python.org/downloads/); on
   Windows tick "Add python.exe to PATH").
2. Copy this folder over, open a terminal in it, and run:

   ```
   python -m pip install -r requirements.txt
   ```

   (On the Mac use `python3` instead of `python`.)

## Run it

Say the PC has the mouse and keyboard and the Mac sits to its **right**:

On the PC (server):
```
python -m mouseshare server --side right --password pick-something
```
It prints its IP address, e.g. `192.168.1.20`.

On the Mac (client):
```
python3 -m mouseshare client --host 192.168.1.20 --password pick-something
```

Now move the mouse off the right edge of the PC screen. To come back, move
off the left edge of the Mac screen.

`--side` is where the *client* screen is relative to the server:
`left`, `right`, `top` or `bottom`. Flip the roles if the mouse is on the Mac.

### First-run permissions

- **Mac**: macOS will block input until you allow it. Open
  *System Settings → Privacy & Security* and turn on your terminal app
  (Terminal, iTerm…) under **Accessibility**, and also under
  **Input Monitoring** if the Mac is the server. Then restart the command.
- **Windows**: allow Python through the firewall when prompted (Private
  networks), or the Mac won't be able to connect.

## Handy details

- **Ctrl ⇄ Cmd** are swapped automatically when the two OSes differ, so
  Ctrl+C on a PC keyboard copies on the Mac, and Cmd+C on a Mac keyboard
  copies on the PC. Turn it off with `--swap-ctrl-cmd off` on the client.
- **Emergency exit**: `Ctrl+Alt+Shift+Esc` always returns the cursor to the
  server. Losing the connection does the same.
- **Scroll feels wrong?** `--scroll-speed 2` for faster, `--scroll-speed -1`
  to flip direction (client side).
- `--no-clipboard` turns off copy/paste sync. `--port` changes the port
  (default 24850) — use the same one on both sides.
- The client reconnects by itself, so you can start the two in either order.

## Limitations

- Traffic is not encrypted. The password stops others connecting, but
  someone sniffing your LAN could read keystrokes. Use it on a trusted network.
- One client at a time; text-only clipboard (no files or images).
- On a Windows server, the PC's own cursor parks in the middle of its screen
  while you're on the Mac (it can't be hidden there).
- Windows won't let a normal program control windows running as
  Administrator. Run the client as Administrator if you need that.
- Ctrl+Alt+Del and the Windows lock screen can't be forwarded.

## Tests

```
python -m unittest discover -s tests
```

The tests run a real server and client over loopback with fake OS hooks, plus
the screen-edge math and key translation tables.

## How it works

The server hooks the OS input stream (pynput event taps on macOS,
low-level hooks on Windows). When the cursor touches the chosen edge it
freezes the local cursor, swallows every local mouse/keyboard event, and
streams relative motion, clicks, scrolls and keys to the client as JSON over
TCP. It tracks a virtual cursor on the client's screen; when that cursor
crosses back over the shared edge, the local cursor is released at the
matching height. Keys travel as layout-neutral names, translated from and to
each OS's key codes (`mouseshare/keymaps.py`).
