"""Command line: `python -m mouseshare server ...` or `python -m mouseshare client ...`."""

import argparse
import socket
import sys

from . import __version__
from .geometry import SIDES
from .protocol import DEFAULT_PORT


def load_platform():
    if sys.platform == "darwin":
        from . import mac as platform
    elif sys.platform == "win32":
        from . import windows as platform
    else:
        sys.exit("mouseshare supports macOS and Windows only.")
    platform.setup()
    return platform


def local_ip():
    """The LAN address other computers can reach us on (no packets are sent)."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("10.255.255.255", 1))
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="mouseshare",
        description="Share one mouse and keyboard between a Mac and a PC.")
    parser.add_argument("--version", action="version", version=__version__)
    roles = parser.add_subparsers(dest="role", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help="TCP port (default %(default)s)")
    common.add_argument("--password", help="shared password; use the same one on both computers")
    common.add_argument("--no-clipboard", action="store_true",
                        help="don't sync copied text between the computers")

    server = roles.add_parser(
        "server", parents=[common],
        help="run on the computer the mouse and keyboard are plugged into")
    server.add_argument("--side", choices=SIDES, required=True,
                        help="where the other screen sits, e.g. 'right' if it's to the right")

    client = roles.add_parser(
        "client", parents=[common], help="run on the computer that borrows them")
    client.add_argument("--host", required=True, help="the server's IP address")
    client.add_argument("--swap-ctrl-cmd", choices=("auto", "on", "off"), default="auto",
                        help="swap Ctrl and Cmd (auto: when the two computers run different OSes)")
    client.add_argument("--scroll-speed", type=float, default=1.0,
                        help="scroll multiplier; negative flips direction (default 1.0)")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    platform = load_platform()

    problems = platform.check_permissions(args.role)
    if problems:
        for problem in problems:
            print(problem)
        return 1

    if not args.password:
        print("Tip: add --password <something> on both computers so nobody else on "
              "the network can connect.")

    try:
        if args.role == "server":
            from .server import Server

            print("Server address: %s  (on the other computer run: python -m mouseshare "
                  "client --host %s)" % (local_ip(), local_ip()))
            print("Emergency: Ctrl+Alt+Shift+Esc brings the cursor back here.")
            Server(platform, args.side, args.port, args.password,
                   share_clipboard=not args.no_clipboard).run()
        else:
            from .client import Client

            return Client(platform, args.host, args.port, args.password,
                          swap=args.swap_ctrl_cmd, share_clipboard=not args.no_clipboard,
                          scroll_speed=args.scroll_speed).run()
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
