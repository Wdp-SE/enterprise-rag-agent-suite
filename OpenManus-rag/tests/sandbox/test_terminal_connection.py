from collections import deque

import pytest

from app.sandbox.core import terminal as terminal_module
from app.sandbox.core.terminal import DockerSession


class RecvSendConnection:
    """Npipe-like public connection surface without a private socket field."""

    def __init__(self, chunks):
        self.chunks = deque(chunks)
        self.sent = []
        self.closed = False

    def recv(self, size):
        return self.chunks.popleft()

    def sendall(self, data):
        self.sent.append(bytes(data))

    def close(self):
        self.closed = True


class ReadWriteConnection:
    """Unix-like file connection surface returned by Docker transports."""

    def __init__(self, chunks):
        self.chunks = deque(chunks)
        self.sent = bytearray()
        self.closed = False
        self.flushed = False

    def read(self, size):
        return self.chunks.popleft()

    def write(self, data):
        self.sent.extend(data)
        return len(data)

    def flush(self):
        self.flushed = True

    def close(self):
        self.closed = True


class UnsupportedConnection:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class FakeAPIClient:
    def __init__(self, connection):
        self.connection = connection

    def exec_create(self, *args, **kwargs):
        return {"Id": "exec-id"}

    def exec_start(self, *args, **kwargs):
        return self.connection

    def exec_inspect(self, exec_id):
        return {"Running": False}


def make_session(monkeypatch, connection):
    api = FakeAPIClient(connection)
    monkeypatch.setattr(terminal_module, "APIClient", lambda: api)
    monkeypatch.setattr(
        terminal_module.uuid,
        "uuid4",
        lambda: type("FixedUUID", (), {"hex": "testmarker"})(),
    )
    return DockerSession("container-id")


@pytest.mark.asyncio
async def test_session_supports_recv_sendall_connection_without_private_socket(
    monkeypatch,
):
    connection = RecvSendConnection(
        [
            b"$ ",
            b"wrapped first command\r\nFirst\r\n",
            b"__OPENMANUS_STATUS_testmarker__:0\r\n$ ",
            b"wrapped second command\r\nSecond\r\n",
            b"__OPENMANUS_STATUS_testmarker__:0\r\n$ ",
        ]
    )
    assert not hasattr(connection, "_sock")
    session = make_session(monkeypatch, connection)

    await session.create("/workspace", {})
    first = await session.execute("echo first")
    second = await session.execute("echo second")
    await session.close()

    assert first == "First"
    assert second == "Second"
    assert len(connection.sent) == 3
    assert all(item.count(b"\n") == 1 for item in connection.sent[:2])
    assert all(
        b"__OPENMANUS_STATUS_testmarker__" in item for item in connection.sent[:2]
    )
    assert connection.sent[-1] == b"exit\n"
    assert connection.closed is True


@pytest.mark.asyncio
async def test_session_preserves_file_like_connection_behavior(monkeypatch):
    connection = ReadWriteConnection(
        [
            b"$ ",
            b"wrapped command\r\nhello\r\n",
            b"__OPENMANUS_STATUS_testmarker__:0\r\n$ ",
        ]
    )
    assert not hasattr(connection, "_sock")
    session = make_session(monkeypatch, connection)

    await session.create("/workspace", {})
    result = await session.execute("echo hello")
    await session.close()

    assert result == "hello"
    assert b"__OPENMANUS_STATUS_testmarker__" in connection.sent
    assert bytes(connection.sent).endswith(b"exit\n")
    assert connection.flushed is True
    assert connection.closed is True


@pytest.mark.asyncio
async def test_session_rejects_connection_without_public_io(monkeypatch):
    connection = UnsupportedConnection()
    session = make_session(monkeypatch, connection)

    with pytest.raises(RuntimeError, match="Unsupported Docker exec connection"):
        await session.create("/workspace", {})

    assert connection.closed is True
