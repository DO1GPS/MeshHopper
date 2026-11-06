"""Start SDK response budgets only after the relay grants device ownership.

The optional Unix socket is installation-local, not a MeshCore wire extension.
Without the environment setting every SDK call retains its original behavior.
No failed device operation is retried here.
"""
from __future__ import annotations

import asyncio
import functools
import json
import math
import os
import re
import uuid
from typing import Any, Callable


ENVIRONMENT = "MESHCORE_COMMAND_ADMISSION_SOCKET"
MAX_RECORD_BYTES = 512
_OPERATIONS = frozenset({"connect", "contacts", "command"})


class AdmissionError(ConnectionError):
    """Ownership could not be proven; the SDK operation was not started."""


class _Admission:
    def __init__(self, client: Any, path: str):
        self.client = client
        self.path = path
        self.lock = asyncio.Lock()
        self.owner_task = None
        self.reader = None
        self.writer = None
        self.grant = None
        self.request_id = None
        self.epoch = None

    def _transport(self):
        manager = getattr(self.client, "connection_manager", None)
        connection = getattr(manager, "connection", None)
        transport = getattr(connection, "transport", None)
        if transport is None or transport.is_closing():
            raise AdmissionError("Command admission requires an open TCP transport")
        return transport

    async def _write(self, value):
        encoded = json.dumps(value, separators=(",", ":")).encode("ascii") + b"\n"
        if len(encoded) > MAX_RECORD_BYTES:
            raise AdmissionError("Command admission record exceeds the local contract")
        self.writer.write(encoded)
        await self.writer.drain()

    async def _read(self):
        try:
            data = await self.reader.readline()
            if not data or len(data) > MAX_RECORD_BYTES or not data.endswith(b"\n"):
                raise AdmissionError("Command admission ended without a complete record")
            value = json.loads(data)
            if not isinstance(value, dict) or type(value.get("v")) is not int or value.get("v") != 1:
                raise AdmissionError("Invalid command admission record")
            return value
        except (ValueError, UnicodeError, asyncio.LimitOverrunError) as exc:
            raise AdmissionError("Invalid command admission record") from exc

    async def _acquire(self, operation):
        transport = self._transport()
        address = transport.get_extra_info("sockname")
        if not isinstance(address, tuple) or len(address) < 2:
            raise AdmissionError("Command admission cannot bind the TCP peer")
        peer_port = address[1]
        if type(peer_port) is not int or not 1 <= peer_port <= 65535:
            raise AdmissionError("Command admission cannot bind the TCP port")
        self.request_id = uuid.uuid4().hex
        self.reader, self.writer = await asyncio.open_unix_connection(
            self.path, limit=MAX_RECORD_BYTES
        )
        await self._write({"v": 1, "op": "reserve", "peer_port": peer_port,
                           "operation": operation, "request_id": self.request_id})
        owner = None
        for _ in range(2):
            reply = await self._read()
            if reply.get("request_id") != self.request_id:
                raise AdmissionError("Command admission request binding changed")
            if type(reply.get("owner")) is not int or reply["owner"] < 1:
                raise AdmissionError("Command admission owner is invalid")
            if owner is not None and owner != reply["owner"]:
                raise AdmissionError("Command admission owner changed while queued")
            owner = reply["owner"]
            if reply.get("status") == "queued":
                continue
            if reply.get("status") != "granted":
                raise AdmissionError("Command admission was rejected")
            if type(reply.get("grant")) is not int or reply["grant"] < 1:
                raise AdmissionError("Command admission grant is invalid")
            if not isinstance(reply.get("epoch"), str) or not re.fullmatch(r"[0-9a-f]{32}", reply["epoch"]):
                raise AdmissionError("Command admission session is invalid")
            if self._transport() is not transport:
                raise AdmissionError("TCP session changed before command admission")
            self.grant = reply["grant"]
            self.epoch = reply["epoch"]
            return
        raise AdmissionError("Command admission did not grant ownership")

    async def _close(self):
        writer = self.writer
        if writer is not None and self.grant is not None:
            try:
                await self._write({"v": 1, "op": "release", "grant": self.grant,
                                   "request_id": self.request_id})
            except (ConnectionError, OSError):
                # Stream closure has the same release/cancellation semantics.
                pass
        self.reader = self.writer = None
        self.grant = self.request_id = self.epoch = None
        if writer is not None:
            # Closing this private control stream cancels pending admission or
            # releases its grant. The relay keeps any dispatched wire request
            # owned until its real reply/deadline; no next-owner reassignment.
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    async def _execute(self, factory, timeout):
        if timeout is None:
            return await factory()
        parent = self.owner_task

        async def runner():
            # Some supported asyncio versions create a child Task in wait_for.
            # Ownership follows only this executing Task, never an inherited
            # ContextVar that would also authorize an unrelated inbox task.
            self.owner_task = asyncio.current_task()
            try:
                return await factory()
            finally:
                self.owner_task = parent

        return await asyncio.wait_for(runner(), timeout=timeout)

    async def call(self, factory: Callable, timeout=None, operation="command", queue_timeout=None):
        if operation not in _OPERATIONS:
            raise ValueError("Unknown command admission operation")
        current = asyncio.current_task()
        if self.owner_task is current:
            return await self._execute(factory, timeout)
        if queue_timeout is not None and (type(queue_timeout) not in (int, float) or
                                          not math.isfinite(queue_timeout) or queue_timeout < 0):
            raise ValueError("Command admission queue timeout must be finite and nonnegative")

        async def acquire():
            await self.lock.acquire()
            try:
                await self._acquire(operation)
            except BaseException:
                try:
                    await self._close()
                finally:
                    self.lock.release()
                raise

        if queue_timeout is None:
            await acquire()
        else:
            # This is an optional caller-owned overall deadline, never a new
            # device response budget. Expiry occurs before the SDK is invoked.
            await asyncio.wait_for(acquire(), timeout=queue_timeout)
        try:
            self.owner_task = current
            return await self._execute(factory, timeout)
        finally:
            self.owner_task = None
            try:
                # Stream closure is the protocol cancellation/release path,
                # including an SDK exception or cancellation after dispatch.
                await self._close()
            finally:
                self.lock.release()


def bind_admission(client, path=None):
    """Bind one SDK client before connect; absent configuration is a no-op.

    Core send is guarded before SDK subscriptions/timers. Multipart contacts
    keeps ownership through the terminal CONTACTS event. Composite helpers
    with their own earlier timers use admitted(..., operation_factory).
    """
    configured = os.environ.get(ENVIRONMENT) if path is None else path
    if not configured:
        return client
    configured = os.fspath(configured)
    if not os.path.isabs(configured):
        raise ValueError("Command admission socket must be an absolute local path")
    old = getattr(client, "_meshcore_command_admission", None)
    if old is not None:
        if old.path != configured:
            raise ValueError("SDK client command admission is already bound")
        return client
    admission = _Admission(client, configured)
    client._meshcore_command_admission = admission
    for name, operation in (("send", "command"), ("get_contacts", "contacts")):
        original = getattr(client.commands, name)

        def make_guard(original, operation):
            @functools.wraps(original)
            async def guarded(*args, **kwargs):
                return await admission.call(lambda: original(*args, **kwargs),
                                            operation=operation)
            return guarded

        setattr(client.commands, name, make_guard(original, operation))
    return client


async def admitted(client, operation_factory, timeout=None, operation="command", queue_timeout=None):
    """Acquire first; only then create the SDK operation and response timer."""
    admission = getattr(client, "_meshcore_command_admission", None)
    if admission is None:
        if timeout is None:
            return await operation_factory()
        return await asyncio.wait_for(operation_factory(), timeout=timeout)
    return await admission.call(operation_factory, timeout, operation, queue_timeout)


async def connect_admitted(client, transport_timeout=None, queue_timeout=None):
    """SDK 2.3.14 connect semantics with admission before its APP_START budget.

    The existing external timeout protects TCP setup, not waiting for another
    device owner. APP_START still uses the original hardcoded two seconds.
    """
    admission = getattr(client, "_meshcore_command_admission", None)
    if admission is None:
        if transport_timeout is None:
            return await client.connect()
        return await asyncio.wait_for(client.connect(), timeout=transport_timeout)
    from meshcore import EventType

    async def start_transport():
        await client.dispatcher.start()
        result = await client.connection_manager.connect()
        if result is None:
            await client.dispatcher.stop()
            raise ConnectionError("Failed to connect to device")

    if transport_timeout is None:
        await start_transport()
    else:
        await asyncio.wait_for(start_transport(), timeout=transport_timeout)
    result = await admitted(client, lambda: client.commands.send_appstart(timeout=2),
                            operation="connect", queue_timeout=queue_timeout)
    if result is None or result.type == EventType.ERROR:
        return None
    return result
