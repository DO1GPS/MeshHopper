"""Own CMD65 attempts, with one Bot writer and a separate WAL database.

Never write raw packet/key material, shared CMD3 observations, or a fake RX.
"""
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys

# Standalone launcher/importlib callers need no SDK or dashboard imports.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from meshcore_process_lock import hold_instance_lock


_STORE_FORMAT = "meshhopper.bot-replies.v1"
_SHARED_HISTORY = Path(__file__).resolve().parents[2] / ".local" / "dashboard-chat.sqlite3"


class ReplyHistoryError(ValueError):
    """An unsafe or unknown store is refused, never migrated or overwritten."""


def _owned_path(path, shared_history_path):
    path = Path(path)
    shared = Path(shared_history_path) if shared_history_path is not None else _SHARED_HISTORY
    # Directory symlinks are intentional in HA; a database-file alias is not.
    if path.is_symlink():
        raise ReplyHistoryError("reply_store_file_symlink_refused")
    resolved = path.resolve()
    if resolved == shared.resolve() or (resolved.exists() and shared.exists()
                                       and os.path.samefile(resolved, shared)):
        raise ReplyHistoryError("shared_chat_store_refused")
    if resolved.exists() and (not resolved.is_file() or resolved.stat().st_nlink > 1):
        raise ReplyHistoryError("reply_store_file_alias_refused")
    return resolved


def _validate_store(path):
    # Existing files are inspected RO: no WAL conversion, DDL or migration.
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=0)) as database:
        if database.execute("PRAGMA journal_mode").fetchone()[0].lower() != "wal":
            raise ReplyHistoryError("reply_store_not_wal")
        objects = database.execute(
            "SELECT type,name FROM sqlite_master WHERE substr(name,1,7) != 'sqlite_' ORDER BY name").fetchall()
        if objects != [("table", "messages"), ("table", "reply_store_meta")]:
            raise ReplyHistoryError("reply_store_schema_unknown")
        for table, expected in (
                ("messages", [(0, "id", "TEXT", 0, None, 1), (1, "payload", "TEXT", 1, None, 0)]),
                ("reply_store_meta", [(0, "key", "TEXT", 0, None, 1), (1, "value", "TEXT", 1, None, 0)])):
            if database.execute(f"PRAGMA table_info({table})").fetchall() != expected:
                raise ReplyHistoryError("reply_store_schema_unknown")
        if database.execute("SELECT key,value FROM reply_store_meta").fetchall() != [("format", _STORE_FORMAT)]:
            raise ReplyHistoryError("reply_store_format_unknown")


def _initialize_store(path):
    if path.exists():
        _validate_store(path)
        return
    # Reserve the new file exclusively; never overwrite a racing foreign file.
    # A failed partial initialization remains visible and is refused next time.
    with path.open("xb"):
        pass
    with closing(sqlite3.connect(path, timeout=0)) as database:
        if database.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower() != "wal":
            raise ReplyHistoryError("reply_store_wal_unavailable")
        database.execute("PRAGMA synchronous=FULL")
        with database:
            database.execute("CREATE TABLE messages (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            database.execute("CREATE TABLE reply_store_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            database.execute("INSERT INTO reply_store_meta VALUES (?,?)", ("format", _STORE_FORMAT))
    _validate_store(path)


@contextmanager
def reply_history_writer(path, *, shared_history_path=None):
    """Hold a canonical store-specific OS lock for the complete Bot lifetime.

    Another checkout/process using this same file fails immediately. The lock
    survives as a file, but its ownership is released on scope exit or crash.
    SQLite still fails closed if an uncooperative foreign writer takes a lock.
    """
    path = _owned_path(path, shared_history_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(path.name + ".writer.lock")
    if lock.is_symlink() or lock.exists() and (not lock.is_file() or lock.stat().st_nlink > 1):
        raise ReplyHistoryError("reply_store_lock_alias_refused")
    with hold_instance_lock(lock):
        # Recheck after obtaining ownership, before initializing any file.
        _owned_path(path, shared_history_path)
        _initialize_store(path)
        yield


def initialize_reply_history(path, *, shared_history_path=None):
    """Initialize/verify before child startup, without retaining a writer lock."""
    with reply_history_writer(path, shared_history_path=shared_history_path):
        pass


_LOCK_LIMIT = 262144
_LOCK_ROW = re.compile(
    r"\d+:[ \t]+(POSIX|FLOCK|OFDLCK)[ \t]+(?:ADVISORY|MANDATORY)[ \t]+(READ|WRITE)[ \t]+"
    r"(-?\d+)[ \t]+([0-9a-fA-F]+):([0-9a-fA-F]+):(\d+)[ \t]+(\d+)[ \t]+(\d+|EOF)")


def _empty_lock_probe():
    return {"state": "unavailable", "sample_phase": "after_connection_close",
            "coverage": "main_file_pid_namespace", "truncated": False, "holders": []}


def _parse_lock_rows(contents, target):
    """Fixed metadata only; waiting locks are not holders. No paths/SQL/argv."""
    holders, partial = [], False
    for line in contents.splitlines():
        if not line.strip() or re.match(r"\d+:\s+->\s", line):
            continue
        match = _LOCK_ROW.fullmatch(line.strip())
        if match is None:
            partial = True
            continue
        kind, access, pid, major, minor, inode, start, end = match.groups()
        if (int(major, 16), int(minor, 16), int(inode)) != target:
            continue
        pid, start = int(pid), int(start)
        end = "EOF" if end == "EOF" else int(end)
        if (pid <= 0 and not (kind == "OFDLCK" and pid == -1)
                or pid >= 2 ** 31 or end != "EOF" and end < start):
            partial = True
            continue
        if len(holders) == 8:
            partial = True
            continue
        holders.append({"pid": pid if pid > 0 else None, "kind": kind,
                        "access": access, "start": start, "end": end, "role": "unknown"})
    return holders, partial


def _holder_role(pid):
    if pid is None:
        return "unknown"
    try:
        with Path(f"/proc/{pid}/cmdline").open("rb") as stream:
            content = stream.read(4097)
        if len(content) > 4096:
            return "unknown"
        # Classify only known executable/script arguments. Never emit argv.
        names = [part.rsplit(b"/", 1)[-1] for part in content.split(b"\0")[:3]]
        if b"meshcore_room_bot.py" in names:
            return "bot"
        if any(name in names for name in (b"message_replay.py", b"meshcore_dashboard_api.py")):
            return "dashboard_api"
        if b"meshcore_multi_client_relay.js" in names:
            return "relay"
    except OSError:
        pass
    return "unknown"


def _lock_probe(path):
    """Failure-only, bounded RO snapshot AFTER SQLite rollback/close.

    PID namespace and main-file coverage are explicit. This can miss a released
    lock or WAL -shm lock; an observed PID is not a proven blocking connection.
    Never use the snapshot for retries, scheduling or changing SQLite settings.
    """
    result = _empty_lock_probe()
    if sys.platform != "linux":
        return result
    try:
        stat = path.stat()
        target = (os.major(stat.st_dev), os.minor(stat.st_dev), stat.st_ino)
        with Path("/proc/locks").open("rb") as stream:
            content = stream.read(_LOCK_LIMIT + 1)
        result["truncated"] = len(content) > _LOCK_LIMIT
        contents = content[:_LOCK_LIMIT].decode("ascii", "replace")
        holders, partial = _parse_lock_rows(contents, target)
        for holder in holders:
            holder["role"] = _holder_role(holder["pid"])
        result["holders"] = holders
        result["state"] = ("partial" if partial or result["truncated"] else
                           "observed" if holders else "none_observed")
    except (OSError, ValueError):
        pass
    return result


def reply_record(reply, status="pending"):
    packet_id = "raw-tx-" + hashlib.sha256(b"\x41\x01" + reply.packet).hexdigest()
    transport_id = "bot-attempt-" + reply.request_identity
    return {"id": transport_id, "transport_id": transport_id, "kind": "channel",
            "packet_id": packet_id, "bot_request_identity": reply.request_identity,
            "channel_index": reply.channel, "contact_prefix": None,
            "sender_timestamp": reply.timestamp, "sender_alias": reply.sender_alias,
            "text": reply.body, "observed_at": datetime.now(timezone.utc).isoformat(),
            "outgoing": True, "source": "bot_raw", "rf_delivery_proven": False,
            "rx_evidence_status": reply.evidence_status,
            "send_result": {"status": status, "accepted": status == "accepted",
                            "delivery_proven": False, "retry_allowed": False,
                            "detail": "accepted_by_local_companion" if status == "accepted" else status}}


def save_reply_record(path: Path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    operation = "connect"
    try:
        with closing(sqlite3.connect(path, timeout=0)) as database:
            operation = "create_table"
            database.execute("CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            # Existing diagnostic category includes connection configuration.
            # DDL stays first so its measured locking boundary is unchanged.
            operation = "connect"
            database.execute("PRAGMA synchronous=FULL")
            with database:
                operation = "insert"
                database.execute("INSERT INTO messages VALUES (?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                                 (record["id"], json.dumps(record, ensure_ascii=False)))
                operation = "commit"  # Existing context manager still commits/rolls back.
    except sqlite3.Error as exc:
        exc.history_operation = operation
        code = getattr(exc, "sqlite_errorcode", None)
        if type(code) is int and code & 255 == sqlite3.SQLITE_BUSY:
            try:
                exc.history_lock_probe = _lock_probe(path)
            except Exception:
                # Diagnostics must never replace the original SQLite error.
                exc.history_lock_probe = _empty_lock_probe()
        raise


def read_reply_records(path: Path):
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0)) as database:
        rows = database.execute("SELECT payload FROM messages ORDER BY rowid").fetchall()
    # Decode only after closing the reader; no decoder work pins a transaction.
    return [json.loads(row[0]) for row in rows]
