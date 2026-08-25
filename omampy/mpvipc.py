"""A small client for mpv's JSON IPC socket.

mpv is the whole backend: it decodes, filters, and plays, and it keeps the
playlist. We drive it over the unix socket it opens with
`--input-ipc-server`. The wire format is one JSON object per line in each
direction, with asynchronous event lines interleaved among the replies, so
the reader has to sort responses from events rather than assume the next line
is the answer.

The socket layer is injectable so the protocol can be tested without mpv.
"""

from __future__ import annotations

import json
import os
import socket
from typing import Any, Iterable


class MpvError(RuntimeError):
    """An error reported by mpv, or a broken conversation with it."""


class ConnectionLost(MpvError):
    """The conversation broke — the socket died rather than mpv saying no.

    Kept distinct from a plain MpvError because a refused property is a
    perfectly normal answer, while a broken socket means the receiver is gone
    and every reading after it would be a lie.
    """


class NotRunning(ConnectionLost):
    """No receiver is listening on the socket."""


def encode(command: Iterable[Any], request_id: int = 1) -> bytes:
    """Serialise one command for the wire."""
    payload = {"command": list(command), "request_id": int(request_id)}
    return (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")


def decode(buffer: bytes) -> tuple[list[dict], bytes]:
    """Split a read buffer into complete messages plus the unterminated rest.

    Undecodable lines are dropped rather than raising: mpv occasionally emits
    log lines on the socket and one of those should not kill playback control.
    """
    messages: list[dict] = []
    while True:
        index = buffer.find(b"\n")
        if index < 0:
            return messages, buffer
        line, buffer = buffer[:index], buffer[index + 1 :]
        text = line.strip()
        if not text:
            continue
        try:
            parsed = json.loads(text.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(parsed, dict):
            messages.append(parsed)


def is_response(message: dict, request_id: int) -> bool:
    """True when `message` is the reply to `request_id` rather than an event."""
    return "event" not in message and message.get("request_id") == request_id


def socket_ready(path: str) -> bool:
    """True when something is listening on the socket at `path`."""
    if not path or not os.path.exists(path):
        return False
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.settimeout(0.4)
        probe.connect(path)
        return True
    except OSError:
        return False
    finally:
        probe.close()


class MpvClient:
    """One short-lived conversation with mpv.

    Used as a context manager; every command opens with a fresh request id so
    a stray event or a late reply from a previous command cannot be mistaken
    for the current answer.
    """

    def __init__(self, path: str, *, timeout: float = 2.0, connector=None):
        self.path = str(path)
        self.timeout = float(timeout)
        self._connector = connector or self._connect_unix
        self._sock = None
        self._buffer = b""
        self._request_id = 0

    def _connect_unix(self, path: str, timeout: float):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(path)
        return sock

    def __enter__(self) -> "MpvClient":
        self.connect()
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def connect(self) -> "MpvClient":
        """Open the socket, or raise NotRunning if nothing is there."""
        if self._sock is not None:
            return self
        try:
            self._sock = self._connector(self.path, self.timeout)
        except (FileNotFoundError, ConnectionRefusedError) as exc:
            raise NotRunning("no receiver on %s" % self.path) from exc
        except OSError as exc:
            raise NotRunning("cannot reach %s: %s" % (self.path, exc)) from exc
        return self

    def close(self) -> None:
        """Hang up. Safe to call twice."""
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        self._buffer = b""

    def command(self, *args: Any) -> Any:
        """Send a command and return its `data`, raising MpvError on failure."""
        self.connect()
        self._request_id += 1
        request_id = self._request_id
        try:
            self._sock.sendall(encode(args, request_id))
        except OSError as exc:
            self.close()
            raise ConnectionLost("send failed: %s" % exc) from exc

        while True:
            messages, self._buffer = decode(self._buffer)
            for message in messages:
                if not is_response(message, request_id):
                    continue
                status = message.get("error", "success")
                if status != "success":
                    raise MpvError("%s: %s" % (" ".join(str(a) for a in args), status))
                return message.get("data")
            try:
                chunk = self._sock.recv(65536)
            except OSError as exc:
                self.close()
                raise ConnectionLost("receive failed: %s" % exc) from exc
            if not chunk:
                self.close()
                raise ConnectionLost("receiver closed the connection")
            self._buffer += chunk

    def get(self, prop: str, default: Any = None) -> Any:
        """Read a property, returning `default` if mpv declines to answer.

        A lost connection is *not* swallowed: silently returning the default
        for every property would make a dead receiver look like a live one
        sitting idle.
        """
        try:
            return self.command("get_property", prop)
        except ConnectionLost:
            raise
        except MpvError:
            return default

    def set(self, prop: str, value: Any) -> Any:
        """Write a property."""
        return self.command("set_property", prop, value)

    def get_many(self, props: Iterable[str]) -> dict:
        """Read several properties, skipping any mpv cannot supply."""
        out = {}
        for prop in props:
            value = self.get(prop, None)
            if value is not None:
                out[prop] = value
        return out
