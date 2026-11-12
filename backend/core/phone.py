"""Phone access: open Grimoire on a phone over the home Wi-Fi.

The main server listens only on this machine (127.0.0.1). When the owner
turns phone access on, a second listener opens on the local network at
PHONE_PORT. Every request through it passes PhoneGate:

- GET /pair?code=... pairs a phone. The code comes from Settings on this
  machine, works once and expires after PAIR_SECONDS. The phone then holds a
  long random token in a cookie. The state file keeps only its SHA-256.
- Any other request needs the cookie of a paired phone.
- The phone settings (/api/phone...) never answer on the phone listener, so
  a phone cannot pair more devices or turn the access off.

The traffic is plain HTTP on the home network, as with any local web app.
"""

import asyncio
import contextlib
import hashlib
import hmac
import json
import logging
import os
import secrets
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import parse_qs

import uvicorn

from backend.core.paths import cache_path

logger = logging.getLogger(__name__)

PHONE_PORT = 8135
PAIR_SECONDS = 600
PAIR_CODE_LENGTH = 6
# The code alphabet leaves out 0/O and 1/I/L, so a typed code reads back right.
PAIR_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
MAX_PAIR_TRIES = 10
COOKIE = "grimoire_phone"
COOKIE_SECONDS = 365 * 24 * 3600
# Paths that the phone listener never serves.
BLOCKED_PREFIX = "/api/phone"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def device_name(user_agent: str) -> str:
    """A short name for a device from its User-Agent, such as "iPhone"."""
    text = user_agent or ""
    for marker, name in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android phone"),
                         ("Macintosh", "Mac"), ("Windows", "Windows PC")):
        if marker in text:
            return name
    return "Device"


def lan_addresses() -> List[str]:
    """The addresses of this machine on the local network, best first.

    The first is the address of the default route (a UDP "connect" sends no
    packet). The machine's .local name follows, for phones that resolve it.
    """
    found = []  # type: List[str]
    with contextlib.suppress(OSError):
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("10.255.255.255", 1))
            address = probe.getsockname()[0]
            if not address.startswith("127."):
                found.append(address)
        finally:
            probe.close()
    with contextlib.suppress(OSError):
        host = socket.gethostname()
        if host and not host.endswith(".local"):
            host += ".local"
        if host:
            found.append(host)
    return found


FIREWALL_TOOL = "/usr/libexec/ApplicationFirewall/socketfilterfw"


def firewall_note(executable: Optional[str] = None) -> Optional[str]:
    """A note when the macOS firewall blocks incoming connections to this Python.

    Then a phone gets "connection reset" before Grimoire sees the request.
    Returns None on other systems, when the check cannot run, or when the
    firewall lets the connections in.
    """
    if sys.platform != "darwin" or not os.path.exists(FIREWALL_TOOL):
        return None
    path = os.path.realpath(executable or sys.executable)
    try:
        result = subprocess.run([FIREWALL_TOOL, "--getappblocked", path], capture_output=True,
                                text=True, timeout=3, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if "is blocked" not in (result.stdout or ""):
        return None
    return (f"The Mac's firewall blocks incoming connections to Python ({path}), so a phone "
            "gets \"connection reset\". Allow it in System Settings, Network, Firewall, "
            "Options. On a work Mac, the IT team may manage this setting.")


class _Server(uvicorn.Server):
    """A uvicorn server that runs inside the main server's event loop.

    It leaves the signal handlers alone: they belong to the main server.
    """

    def capture_signals(self):
        return contextlib.nullcontext()


class PhoneAccess:
    """The phone access state, the pairing codes and the phone listener."""

    def __init__(self, state_file: Optional[Path] = None, port: int = PHONE_PORT):
        self.state_file = Path(state_file) if state_file else cache_path("phone.json")
        self.port = port
        self._state = self._load()
        self._pair = None  # type: Optional[Dict]
        self._server = None  # type: Optional[_Server]
        self._task = None  # type: Optional[asyncio.Task]
        self.last_error = None  # type: Optional[str]

    # ---- state ---------------------------------------------------------------

    def _load(self) -> Dict:
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        devices = data.get("devices") if isinstance(data.get("devices"), list) else []
        return {"enabled": data.get("enabled") is True, "devices": devices}

    def _save(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_name(f".{self.state_file.name}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(self._state, indent=2), encoding="utf-8")
        os.replace(tmp, self.state_file)

    @property
    def enabled(self) -> bool:
        return self._state["enabled"]

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def devices(self) -> List[Dict]:
        """The paired devices, without their token hashes."""
        return [{"id": d["id"], "name": d.get("name", "Device"), "created": d.get("created", "")}
                for d in self._state["devices"]]

    def status(self) -> Dict:
        addresses = lan_addresses()
        pair = self.pair_info(addresses)
        return {"enabled": self.enabled, "running": self.running, "port": self.port,
                "urls": [f"http://{a}:{self.port}" for a in addresses],
                "devices": self.devices(), "pair": pair, "error": self.last_error,
                "firewall": firewall_note() if self.running else None}

    # ---- pairing -------------------------------------------------------------

    def new_pair_code(self) -> str:
        """Make a new pairing code. It replaces the one before."""
        code = "".join(secrets.choice(PAIR_ALPHABET) for _ in range(PAIR_CODE_LENGTH))
        self._pair = {"code": code, "expires": time.time() + PAIR_SECONDS, "tries": 0}
        return code

    def pair_info(self, addresses: Optional[List[str]] = None) -> Optional[Dict]:
        """The live pairing code and its link, or None."""
        if not self._pair or self._pair["expires"] <= time.time():
            return None
        addresses = lan_addresses() if addresses is None else addresses
        url = (f"http://{addresses[0]}:{self.port}/pair?code={self._pair['code']}"
               if addresses else "")
        return {"code": self._pair["code"], "url": url,
                "expires_in": int(self._pair["expires"] - time.time())}

    def pair(self, code: str, user_agent: str = "") -> Optional[str]:
        """Pair a device with a code. Return its new token, or None.

        A code works once. After MAX_PAIR_TRIES wrong codes the live code
        stops working, so a guess cannot run for the whole PAIR_SECONDS.
        """
        pair = self._pair
        if not self.enabled or not pair or pair["expires"] <= time.time():
            return None
        if not hmac.compare_digest(str(code or "").strip().upper(), pair["code"]):
            pair["tries"] += 1
            if pair["tries"] >= MAX_PAIR_TRIES:
                self._pair = None
            return None
        self._pair = None
        token = secrets.token_urlsafe(32)
        self._state["devices"].append({
            "id": uuid.uuid4().hex[:12], "name": device_name(user_agent),
            "created": datetime.now(timezone.utc).isoformat(), "token": _hash(token)})
        self._save()
        return token

    def is_paired(self, token: Optional[str]) -> bool:
        if not token or not self.enabled:
            return False
        digest = _hash(token)
        return any(hmac.compare_digest(digest, d.get("token", "")) for d in self._state["devices"])

    def forget(self, device_id: Optional[str] = None) -> bool:
        """Unpair one device, or every device when device_id is None."""
        before = len(self._state["devices"])
        if device_id is None:
            self._state["devices"] = []
        else:
            self._state["devices"] = [d for d in self._state["devices"] if d["id"] != device_id]
        self._save()
        return len(self._state["devices"]) < before

    # ---- the phone listener --------------------------------------------------

    async def set_enabled(self, app, enabled: bool) -> None:
        """Turn phone access on or off, and start or stop the listener."""
        self._state["enabled"] = enabled
        self._save()
        if enabled:
            await self.start(app)
        else:
            self._pair = None
            await self.stop()

    async def start(self, app) -> None:
        """Start the phone listener, unless it runs. A port in use sets last_error."""
        if self.running:
            return
        self.last_error = None
        # Open the socket here: uvicorn ends the whole process (sys.exit) when
        # it cannot bind, and that would stop the main server too.
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", self.port))
        except OSError:
            sock.close()
            self.last_error = (f"Port {self.port} is in use, so phones cannot connect. "
                               "Close the program that uses it, then try again.")
            return
        config = uvicorn.Config(PhoneGate(app, self), lifespan="off", log_level="warning")
        server = _Server(config)
        task = asyncio.create_task(server.serve(sockets=[sock]))
        # Wait until the listener is up.
        for _ in range(100):
            if server.started or task.done():
                break
            await asyncio.sleep(0.05)
        if task.done() or not server.started:
            self.last_error = "The phone listener did not start. Restart Grimoire, then try again."
            server.should_exit = True
            with contextlib.suppress(Exception, asyncio.CancelledError):
                await asyncio.wait_for(task, 2)
            sock.close()
            return
        self._server, self._task = server, task

    async def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._task is not None:
            with contextlib.suppress(BaseException):
                await asyncio.wait_for(self._task, 5)
        self._server, self._task = None, None


# ---- the gate of the phone listener --------------------------------------------

_LOCKED_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Grimoire</title><style>body{{font:16px/1.5 system-ui,sans-serif;background:#12152a;
color:#e8e6f0;margin:0;padding:32px 20px}}h1{{font-size:1.3rem;color:#e8c26a}}</style></head>
<body><h1>{title}</h1><p>{text}</p></body></html>"""
NOT_PAIRED = ("This phone is not paired",
              "On your computer, open Grimoire, go to Settings, then Phone access, "
              "and scan the QR code with this phone.")
BAD_CODE = ("This pairing link does not work",
            "The code is old, used, or wrong. On your computer, make a new code in "
            "Settings, then Phone access, and scan it again.")


class PhoneGate:
    """ASGI middleware of the phone listener: only paired phones get in."""

    def __init__(self, app, access: PhoneAccess):
        self.app = app
        self.access = access

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            return
        if scope["type"] not in ("http", "websocket"):
            return
        path = scope.get("path", "")
        headers = {k.decode("latin-1").lower(): v.decode("latin-1")
                   for k, v in scope.get("headers", [])}
        if scope["type"] == "http" and path == "/pair":
            await self._pair(scope, headers, send)
            return
        token = None
        cookie = SimpleCookie()
        with contextlib.suppress(Exception):
            cookie.load(headers.get("cookie", ""))
            if COOKIE in cookie:
                token = cookie[COOKIE].value
        if path.startswith(BLOCKED_PREFIX) or not self.access.is_paired(token):
            if scope["type"] == "http":
                await self._locked(path, send, NOT_PAIRED)
            return
        await self.app(scope, receive, send)

    async def _pair(self, scope, headers: Dict[str, str], send) -> None:
        query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
        code = (query.get("code") or [""])[0]
        token = self.access.pair(code, headers.get("user-agent", ""))
        if token is None:
            await self._locked("/pair", send, BAD_CODE, status=403)
            return
        cookie = (f"{COOKIE}={token}; Max-Age={COOKIE_SECONDS}; Path=/; HttpOnly; "
                  "SameSite=Lax")
        await send({"type": "http.response.start", "status": 303,
                    "headers": [(b"location", b"/"), (b"set-cookie", cookie.encode("latin-1")),
                                (b"cache-control", b"no-store")]})
        await send({"type": "http.response.body", "body": b""})

    @staticmethod
    async def _locked(path: str, send, message, status: int = 401) -> None:
        title, text = message
        if path.startswith("/api/"):
            body = json.dumps({"detail": f"{title}. {text}"}).encode("utf-8")
            kind = b"application/json"
        else:
            body = _LOCKED_PAGE.format(title=title, text=text).encode("utf-8")
            kind = b"text/html; charset=utf-8"
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", kind), (b"cache-control", b"no-store")]})
        await send({"type": "http.response.body", "body": body})
