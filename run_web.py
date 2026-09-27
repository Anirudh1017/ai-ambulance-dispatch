"""Entry point: web dashboard (FastAPI + WebSocket + HTML5 Canvas)."""

import socket
import sys

import uvicorn

HOST = "127.0.0.1"
PORT = 8000
URL = f"http://{HOST}:{PORT}/"


def _port_is_open(host: str = HOST, port: int = PORT) -> bool:
    """True when something is already accepting connections on the port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        return sock.connect_ex((host, port)) == 0


def main() -> int:
    # A stale server on the port makes uvicorn die with WinError 10048, which
    # looks like an instant crash when double-clicked. Say what is going on.
    if _port_is_open():
        print(f"[INFO] Port {PORT} is already in use - a server is already running.")
        print(f"       The dashboard is live at: {URL}")
        print("       Nothing to start. If it looks stale, stop it with:")
        print(f"         netstat -ano | findstr :{PORT}")
        print("         taskkill /PID <pid> /F")
        return 0

    print(f"Starting FOAI dashboard at {URL}")
    print("Press Ctrl+C to stop.")
    uvicorn.run("web.main:app", host=HOST, port=PORT, reload=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
