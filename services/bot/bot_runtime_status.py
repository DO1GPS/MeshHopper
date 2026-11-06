"""Bounded last-observed Bot lifecycle; not a heartbeat or RF proof.

One writer owns the unchanged instance lock. Readers require its exact Linux
FLOCK owner, boot identifier and process start ticks, never a PID alone. Any
missing proof is unknown. No SDK, timers, database, secrets or network calls.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import time
import uuid

from bot_commands import COMMAND_FAMILIES


SCHEMA = "meshhopper.bot-runtime.v1"
MAX_STATUS_BYTES = 4096
MAX_PROC_LOCK_BYTES = 262144
LIFECYCLES = frozenset({"starting", "profile_ready", "connected", "disconnected", "stopped"})
_HEX32 = re.compile(r"[0-9a-f]{32}")
_LOCK_ROW = re.compile(
    r"\d+:\s+FLOCK\s+ADVISORY\s+WRITE\s+(\d+)\s+"
    r"([0-9a-fA-F]+):([0-9a-fA-F]+):(\d+)\s+0\s+EOF")
_FIELDS = frozenset({"schema", "owner", "process_id", "session_id", "revision",
                    "observed_at", "lifecycle", "channels", "reply_mode", "commands"})


def _hex32(value):
    return type(value) is str and _HEX32.fullmatch(value) is not None


def _owner_valid(value):
    return (type(value) is dict and set(value) == {"pid", "start_ticks", "boot_id"}
            and type(value["pid"]) is int and 0 < value["pid"] < 2 ** 31
            and type(value["start_ticks"]) is int and 0 < value["start_ticks"] < 2 ** 64
            and _hex32(value["boot_id"]))


def _read_limited(path, maximum):
    with Path(path).open("rb") as stream:
        value = stream.read(maximum + 1)
    if len(value) > maximum:
        raise ValueError("bounded_read_exceeded")
    return value


def _process_marker(pid, proc_root):
    if type(pid) is not int or not 0 < pid < 2 ** 31:
        return None
    stat = _read_limited(proc_root / str(pid) / "stat", 4096).decode("ascii", "strict")
    # comm may contain spaces and parentheses. Fields following its final ')'
    # start at field 3 (state); starttime is field 22, index 19 in this tail.
    close = stat.rfind(")")
    if close < 0 or stat.partition(" ")[0] != str(pid):
        return None
    fields = stat[close + 1:].split()
    if len(fields) < 20 or fields[0] in {"Z", "X", "x"}:
        return None
    start = int(fields[19])
    boot = _read_limited(proc_root / "sys/kernel/random/boot_id", 64).decode("ascii", "strict").strip()
    marker = {"pid": pid, "start_ticks": start, "boot_id": uuid.UUID(boot).hex}
    return marker if _owner_valid(marker) else None


def linux_owner_probe(pid, lock_path, *, proc_root=Path("/proc")):
    """Return only a proven current owner marker, or None (including races).

    All reads are bounded. Lock inode and process start are compared on both
    sides of /proc/locks. A truncated table is unknown, never partial success.
    This does not create/open-acquire the lock or inspect private process argv.
    """
    try:
        if os.name != "posix" and proc_root == Path("/proc"):
            return None
        proc_root, lock_path = Path(proc_root), Path(lock_path)
        before = _process_marker(pid, proc_root)
        if before is None or lock_path.is_symlink():
            return None
        stat = lock_path.stat()
        if not lock_path.is_file() or stat.st_nlink != 1:
            return None
        target = (os.major(stat.st_dev), os.minor(stat.st_dev), stat.st_ino)
        content = _read_limited(proc_root / "locks", MAX_PROC_LOCK_BYTES).decode("ascii", "strict")
        holders = []
        for line in content.splitlines():
            if re.match(r"\d+:\s+->\s", line):
                continue  # A waiting lock is not an owner.
            match = _LOCK_ROW.fullmatch(line.strip())
            if match and tuple((int(match[2], 16), int(match[3], 16), int(match[4]))) == target:
                holders.append(int(match[1]))
        after_stat = lock_path.stat()
        after = _process_marker(pid, proc_root)
        if (holders != [pid] or after != before
                or (after_stat.st_dev, after_stat.st_ino, after_stat.st_nlink)
                   != (stat.st_dev, stat.st_ino, 1)):
            return None
        return before
    except (OSError, ValueError, UnicodeError, IndexError, OverflowError):
        return None


def _valid_snapshot(value):
    if type(value) is not dict or set(value) != _FIELDS or value.get("schema") != SCHEMA:
        return False
    if not _owner_valid(value["owner"]) or not _hex32(value["process_id"]):
        return False
    if value["session_id"] is not None and not _hex32(value["session_id"]):
        return False
    if (type(value["revision"]) is not int or not 1 <= value["revision"] < 2 ** 63
            or type(value["observed_at"]) is not int or not 0 <= value["observed_at"] < 2 ** 63
            or value["lifecycle"] not in LIFECYCLES
            or value["reply_mode"] not in {"legacy", "raw_qsl"}):
        return False
    channels = value["channels"]
    if (type(channels) is not list or not 1 <= len(channels) <= 256
            or any(type(index) is not int or not 0 <= index <= 255 for index in channels)
            or channels != sorted(set(channels))):
        return False
    if (type(value["commands"]) is not list
            or value["commands"] != sorted(COMMAND_FAMILIES)):
        return False
    if value["lifecycle"] in {"profile_ready", "connected", "disconnected"} and value["session_id"] is None:
        return False
    return True


def _unavailable(reason):
    return {"status": "unavailable", "reason": reason, "snapshot": None}


def load_runtime_status(path, *, held, owner_probe=None):
    """Strict RO projection of an owned last-observed snapshot.

    held is the existing independent OS-lock probe, not file/PID existence.
    owner_probe(pid, lock_path) is injectable for offline/Windows tests.
    No current timestamps are invented and no state is repaired on a GET.
    """
    if held is not True:
        return _unavailable("instance_not_proven")
    path = Path(path)
    try:
        if path.is_symlink():
            return _unavailable("status_file_alias_refused")
        stat = path.stat()
        if not path.is_file() or stat.st_nlink != 1:
            return _unavailable("status_file_alias_refused")
        value = json.loads(_read_limited(path, MAX_STATUS_BYTES).decode("utf-8", "strict"))
        if not _valid_snapshot(value):
            return _unavailable("invalid_status_snapshot")
        probe = owner_probe or linux_owner_probe
        if probe(value["owner"]["pid"], path.with_name("room-bot.lock")) != value["owner"]:
            return _unavailable("owner_not_proven")
        return {"status": "available", "reason": "owned_last_observed", "snapshot": value}
    except FileNotFoundError:
        return _unavailable("status_missing")
    except Exception:
        return _unavailable("status_read_unavailable")


class RuntimeStatusWriter:
    """Best-effort bounded transition writer; never part of send admission."""

    def __init__(self, path, *, channels, reply_mode, commands, lock_path,
                 owner_probe=None, clock=time.time, pid=None, identity_factory=None):
        self.path, self.lock_path = Path(path), Path(lock_path)
        self.channels, self.reply_mode = sorted(channels), reply_mode
        self.commands = sorted(commands)
        self.probe, self.clock = owner_probe or linux_owner_probe, clock
        self.pid = os.getpid() if pid is None else pid
        self.identity_factory = identity_factory or (lambda: uuid.uuid4().hex)
        self.process_id = self.identity_factory()
        self.owner = self.probe(self.pid, self.lock_path)
        self.session_id = None
        self.revision = 0
        self._last_transition = None

    def _atomic_write(self, encoded):
        # The parent is the already-owned runtime directory. Never create or
        # rebind runtime ownership, overwrite an alias or reuse an old temp.
        if self.path.is_symlink() or self.path.exists() and (
                not self.path.is_file() or self.path.stat().st_nlink != 1):
            raise ValueError("status_file_alias_refused")
        temporary = self.path.with_name("." + self.path.name + "." + self.identity_factory() + ".tmp")
        created = False
        try:
            with temporary.open("xb") as stream:
                created = True
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if created and temporary.exists():
                temporary.unlink()  # Only this call's exclusively created file.

    def transition(self, lifecycle, *, new_session=False):
        """Return diagnostic success only; callers must ignore failure for RF."""
        try:
            if lifecycle not in LIFECYCLES:
                return False
            session = self.identity_factory() if new_session else self.session_id
            if self._last_transition == (lifecycle, session):
                return True  # No duplicate heartbeat/event write.
            self.session_id = session
            if not _owner_valid(self.owner) or self.probe(self.pid, self.lock_path) != self.owner:
                return False
            snapshot = {"schema": SCHEMA, "owner": self.owner, "process_id": self.process_id,
                        "session_id": session, "revision": self.revision + 1,
                        "observed_at": int(self.clock()), "lifecycle": lifecycle,
                        "channels": self.channels, "reply_mode": self.reply_mode,
                        "commands": self.commands}
            if not _valid_snapshot(snapshot):
                return False
            encoded = json.dumps(snapshot, ensure_ascii=True, separators=(",", ":")).encode("ascii")
            if len(encoded) > MAX_STATUS_BYTES:
                return False
            self._atomic_write(encoded)
            self.revision += 1
            self._last_transition = (lifecycle, session)
            return True
        except Exception:
            return False  # Diagnostics never alter connection/send behavior.
