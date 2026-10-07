"""Reliable, narrowly scoped auto-reply bot for a MeshCore test room.

The bot connects only to the local multi-client relay (default TCP 5102),
never directly to the single-session BLE bridge (5101).  It replies only to
bounded channel commands from the shared ping/test/room grammar.

An ``OK`` reply from the local M1 means only that the M1 accepted the command;
it is not RF delivery proof.  All state changes are logged without message
contents, channel secrets, credentials or contact identifiers.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import signal
import sqlite3
import sys
import time
from contextlib import closing, ExitStack, nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services"))
from meshcore_process_lock import InstanceAlreadyRunningError, hold_instance_lock  # noqa: E402

sys.path.insert(0, str(ROOT / ".deps"))
# The sandbox-owned development dependencies may deliberately be unreadable
# from the normal Windows user account. Prefer the installed companion runtime
# when it is accessible; do not relax the sandbox's filesystem permissions.
runtime_deps = Path(os.environ.get("LOCALAPPDATA", "")) / "DO1GPS" / "MeshCoreM1Bridge" / "python-deps"
try:
    if (runtime_deps / "meshcore" / "__init__.py").is_file():
        sys.path.insert(0, str(runtime_deps))
except PermissionError:
    pass

from meshcore import EventType, MeshCore, TCPConnection  # noqa: E402
from meshcore_inbox_fetch import InboxFetcher  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from report_profile import read_report_engine  # noqa: E402
from raw_reply_history import reply_record, save_reply_record, reply_history_writer  # noqa: E402
from report_engine import command_identity  # noqa: E402
from bot_identity import BOT_NAME  # noqa: E402
from bot_commands import parse_command  # noqa: E402


BOT_PREFIX = f"[{BOT_NAME}]"
COMMAND_REPLIES = {
    "ping": f"{BOT_PREFIX} PONG",
    "test": f"{BOT_PREFIX} TEST OK",
    "room": f"{BOT_PREFIX} ROOM OK",
}
DEFAULT_CHANNELS = frozenset({2, 5, 7})


def exact_command(text: object) -> str | None:
    """Recognize received group text without changing its raw identity."""
    return parse_command(text, wire=True)


def message_fingerprint(channel: int, timestamp: int, text: str) -> str:
    safe = f"{channel}:{timestamp}:{text}".encode("utf-8", "replace")
    return hashlib.sha256(safe).hexdigest()[:16]


class DuplicateWindow:
    """Suppress retransmissions of the same received packet, not new commands."""

    def __init__(self, seconds: float = 600.0) -> None:
        self.seconds = seconds
        self._expires: dict[str, float] = {}

    def seen(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        self._expires = {item: expiry for item, expiry in self._expires.items() if expiry > now}
        if key in self._expires:
            return True
        self._expires[key] = now + self.seconds
        return False


class PersistentDuplicateWindow:
    """Commit a claim before a send attempt, surviving process restarts.

    The existing ten-minute duplicate window is unchanged. A committed claim
    is not delivery proof; uncertain/failed sends are deliberately not retried.
    No message bodies or channel secrets are persisted.
    """

    def __init__(self, path: Path, seconds: float = 600.0) -> None:
        self.path = path
        self.seconds = seconds

    def seen(self, key: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=0)) as database:
            database.execute("PRAGMA synchronous=FULL")
            database.execute("CREATE TABLE IF NOT EXISTS claims (key TEXT PRIMARY KEY, expires REAL NOT NULL)")
            with database:
                database.execute("BEGIN IMMEDIATE")
                database.execute("DELETE FROM claims WHERE expires <= ?", (now,))
                inserted = database.execute(
                    "INSERT OR IGNORE INTO claims VALUES (?, ?)", (key, now + self.seconds)
                ).rowcount
            return inserted == 0


class ClaimCapacityError(sqlite3.DatabaseError):
    """No forgotten claims or automatic retries when the permanent ledger fills."""


class PermanentCommandClaims:
    """Raw-mode at-most-once claims: bounded, durable, no time-based eviction.

    A full ledger rejects new requests visibly. It never forgets a processed
    command merely to admit another. None path is the non-persistent dry run.
    Existing legacy claims/table are not modified.
    """
    def __init__(self, path: Path | None, max_claims: int = 65536):
        if type(max_claims) is not int or not 1 <= max_claims <= 65536:
            raise ValueError("Invalid claim capacity")
        self.path, self.max_claims = path, max_claims
        self._memory = set()
        self._packets = set()

    def seen(self, key: str, now: float | None = None):
        if not isinstance(key, str) or len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
            raise ValueError("Invalid command identity")
        if self.path is None:
            if key in self._memory:
                return True
            if len(self._memory) >= self.max_claims:
                raise ClaimCapacityError("permanent_claim_capacity_reached")
            self._memory.add(key)
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=0)) as database:
            database.execute("PRAGMA synchronous=FULL")
            database.execute("CREATE TABLE IF NOT EXISTS raw_claims (key TEXT PRIMARY KEY)")
            with database:
                database.execute("BEGIN IMMEDIATE")
                if database.execute("SELECT 1 FROM raw_claims WHERE key=?", (key,)).fetchone():
                    return True
                if database.execute("SELECT count(*) FROM raw_claims").fetchone()[0] >= self.max_claims:
                    raise ClaimCapacityError("permanent_claim_capacity_reached")
                database.execute("INSERT INTO raw_claims VALUES (?)", (key,))
            return False

    def reserve_packet(self, key: str):
        """Durable payload reservation, separate from original command claims.

        False means an identical wire payload was reserved already. No claim
        eviction, message/secret storage, timestamp invention or RF retry.
        """
        if not isinstance(key, str) or len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
            raise ValueError("Invalid outgoing packet identity")
        if self.path is None:
            if key in self._packets:
                return False
            if len(self._packets) >= self.max_claims:
                raise ClaimCapacityError("permanent_packet_capacity_reached")
            self._packets.add(key)
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=0)) as database:
            database.execute("PRAGMA synchronous=FULL")
            database.execute("CREATE TABLE IF NOT EXISTS raw_packet_claims (key TEXT PRIMARY KEY)")
            with database:
                database.execute("BEGIN IMMEDIATE")
                if database.execute("SELECT 1 FROM raw_packet_claims WHERE key=?", (key,)).fetchone():
                    return False
                if database.execute("SELECT count(*) FROM raw_packet_claims").fetchone()[0] >= self.max_claims:
                    raise ClaimCapacityError("permanent_packet_capacity_reached")
                database.execute("INSERT INTO raw_packet_claims VALUES (?)", (key,))
            return True
def parse_channels(value: str | None) -> frozenset[int]:
    """Parse a comma-separated allowlist of MeshCore channel indexes."""
    if value is None or not value.strip():
        return DEFAULT_CHANNELS
    try:
        channels = frozenset(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        raise ValueError("MESHCORE_BOT_CHANNELS must be comma-separated indexes") from exc
    if not channels or any(channel < 0 or channel > 255 for channel in channels):
        raise ValueError("MESHCORE_BOT_CHANNELS must contain indexes from 0 to 255")
    return channels


@dataclass(frozen=True)
class BotConfig:
    host: str
    port: int
    channels: frozenset[int]
    log_file: Path
    live: bool
    reply_mode: str = "legacy"
    history_path: Path = ROOT / ".local" / "bot-replies.sqlite3"
    inbox_owner: str = "bot"

    def __post_init__(self):
        if self.reply_mode not in ("legacy", "raw_qsl"):
            raise ValueError("Unknown bot reply mode")
        if self.inbox_owner not in ("bot", "dashboard-api"):
            raise ValueError("Unknown inbox owner")

    @classmethod
    def from_environment(cls, live: bool) -> "BotConfig":
        port = int(os.environ.get("MESHCORE_BOT_PORT", "5102"))
        if not 1 <= port <= 65535:
            raise ValueError("MESHCORE_BOT_PORT must be a TCP port")
        return cls(
            host=os.environ.get("MESHCORE_BOT_HOST", "127.0.0.1"),
            port=port,
            channels=parse_channels(os.environ.get("MESHCORE_BOT_CHANNELS")),
            log_file=Path(
                os.environ.get(
                    "MESHCORE_BOT_LOG",
                    str(ROOT / "services" / "bot" / "runtime" / "room-bot.log"),
                )
            ),
            live=live,
            reply_mode=os.environ.get("MESHCORE_BOT_REPLY_MODE", "legacy"),
            history_path=Path(os.environ.get("MESHCORE_BOT_HISTORY", str(ROOT / ".local" / "bot-replies.sqlite3"))),
            inbox_owner=os.environ.get("MESHCORE_INBOX_OWNER", "bot"),
        )


class RoomBot:
    def __init__(self, config: BotConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
        self.duplicates = (PersistentDuplicateWindow(config.log_file.with_name("room-bot-seen.sqlite3"))
                           if config.live else DuplicateWindow())
        if config.reply_mode == "raw_qsl":
            self.duplicates = PermanentCommandClaims(
                config.log_file.with_name("room-bot-seen.sqlite3") if config.live else None)
        self.session_started_at = int(time.time())
        self._send_lock = asyncio.Lock()
        self._active_reports = set()
        self.client: MeshCore | None = None
        self.report_engine = None
        self._session_token = object()

    def observe_raw_reception(self, event: Any) -> None:
        # Synchronous callback: do not enqueue RX decoding behind the channel
        # handler. Never borrow the SDK's short packet-hash correlation cache.
        if self.report_engine is None:
            return
        payload = getattr(event, "payload", {})
        value = payload.get("raw_hex") if isinstance(payload, dict) else None
        try:
            if not isinstance(value, str):
                raise ValueError("Missing raw data")
            result = self.report_engine.observe(b"\x88" + bytes.fromhex(value))
        except (ValueError, TypeError):
            self.log("raw_evidence_unavailable", reason="invalid_raw_frame")
            return
        if result.reason != "not_a_command":
            self.log("raw_evidence_observed", status=result.status, reason=result.reason)

    async def send_report(self, channel, timestamp, text, command, fingerprint):
        if self.report_engine is None:
            self.log("reply_skipped_profile_unavailable", channel=channel, fingerprint=fingerprint)
            return
        engine = self.report_engine
        client, session_token = self.client, self._session_token
        phase, rf_attempted = "prepare", False
        try:
            async with self._send_lock:
                last_second = None
                for collision in range(3):
                    if (session_token is not self._session_token or client is not self.client
                            or engine is not self.report_engine or client is None):
                        self.log("reply_skipped_session_changed", channel=channel, fingerprint=fingerprint)
                        return
                    manager = getattr(client, "connection_manager", None)
                    if manager is not None and manager.is_connected is not True:
                        self.log("reply_skipped_transport_unavailable", channel=channel, fingerprint=fingerprint)
                        return
                    now = time.time()
                    second = int(now)
                    if last_second is not None and second < last_second:
                        self.log("reply_skipped_clock_rollback", channel=channel, fingerprint=fingerprint)
                        return
                    last_second = second
                    # Re-read exact RX after each wait: a new copy may have
                    # made reception ambiguous or unavailable in the meantime.
                    phase = "prepare"
                    reply = engine.build(channel, timestamp, text, command, second)
                    phase = "packet_claim_before_send"
                    if self.duplicates.reserve_packet(reply.packet_identity):
                        break
                    if collision == 2:
                        self.log("reply_skipped_packet_collision", channel=channel,
                                 fingerprint=fingerprint, rf_attempted=False)
                        return
                    wait = max(0.01, 1.0 - (now - second))
                    self.log("packet_collision_wait", channel=channel, fingerprint=fingerprint,
                             collision=collision + 1, requested_wait_ms=round(wait * 1000))
                    started = time.monotonic()
                    await asyncio.sleep(wait)
                    self.log("packet_collision_wait_completed", channel=channel, fingerprint=fingerprint,
                             collision=collision + 1,
                             elapsed_wait_ms=round((time.monotonic() - started) * 1000))
                record = reply_record(reply)
                # Persist the uncertain attempt before sending, separately
                # from the relay's CMD3-only outgoing ledger.
                phase = "history_before_send"
                save_reply_record(self.config.history_path, record)
                self.log("reply_requested", channel=channel, command=command, fingerprint=fingerprint,
                         sender_alias=reply.sender_alias, rx_evidence_status=reply.evidence_status,
                         transport="raw_qsl_default_scope")
                try:
                    phase, rf_attempted = "send", True
                    response = await client.commands.send_raw_packet(reply.packet, priority=1)
                    status = ("accepted" if response is not None and response.type == EventType.OK else
                              "rejected" if response is not None and response.type == EventType.ERROR else
                              "unknown_response")
                except Exception as exc:
                    status = "unknown_after_transport_error"
                    self.log("reply_failed", channel=channel, fingerprint=fingerprint, error_type=type(exc).__name__)
                record["send_result"] = reply_record(reply, status)["send_result"]
                phase = "history_after_send"
                save_reply_record(self.config.history_path, record)
                self.log("reply_accepted_by_local_m1" if status == "accepted" else "reply_not_accepted",
                         channel=channel, command=command, fingerprint=fingerprint,
                         sender_alias=reply.sender_alias, rf_delivery_proven=False, result=status)
        except (OSError, sqlite3.Error, ValueError, UnicodeError) as exc:
            self.log("report_preparation_or_history_failed", channel=channel,
                     command=command, fingerprint=fingerprint, error_type=type(exc).__name__,
                     phase=phase, rf_attempted=rf_attempted,
                     sqlite_errorcode=getattr(exc, "sqlite_errorcode", None),
                     sqlite_errorname=getattr(exc, "sqlite_errorname", None),
                     history_operation=getattr(exc, "history_operation", None),
                     history_lock_probe=getattr(exc, "history_lock_probe", None))
        finally:
            engine.complete(channel, timestamp, text)

    def log(self, event: str, **fields: object) -> None:
        record = {"time": int(time.time()), "event": event, **fields}
        self.logger.info(json.dumps(record, ensure_ascii=True, sort_keys=True))

    @staticmethod
    def _event_fingerprint(payload: dict[str, Any]) -> str:
        return message_fingerprint(
            int(payload.get("channel_idx", -1)),
            int(payload.get("sender_timestamp", 0)),
            str(payload.get("text", "")),
        )

    async def observe_messages_waiting(self, event: Any) -> None:
        self.log("messages_waiting")

    async def observe_contact_message(self, event: Any) -> None:
        payload = event.payload if isinstance(getattr(event, "payload", None), dict) else {}
        self.log("contact_message_observed", fingerprint=self._event_fingerprint(payload))

    async def handle_channel_message(self, event: Any, *, session_token=None) -> None:
        if session_token is not None and session_token is not self._session_token:
            self.log("ignored_old_session_event")
            return
        payload = event.payload if isinstance(getattr(event, "payload", None), dict) else {}
        channel = payload.get("channel_idx")
        text = payload.get("text")
        timestamp = payload.get("sender_timestamp")
        if not isinstance(channel, int) or not isinstance(timestamp, int) or not isinstance(text, str):
            self.log("ignored_invalid_message")
            return
        command = exact_command(text)
        self.log(
            "channel_message_observed",
            channel=channel,
            command=command or "other",
            fingerprint=self._event_fingerprint(payload),
            has_sender_prefix=": " in text,
            text_bytes=len(text.encode("utf-8")),
            age_seconds=int(time.time()) - timestamp,
        )
        if channel not in self.config.channels:
            return
        if text.startswith(BOT_PREFIX):
            self.log("ignored_bot_echo", channel=channel)
            return
        if command is None:
            return
        # Messages fetched during startup can be old inbox entries.  Never
        # answer these retrospectively; an operator's new command has a fresh
        # MeshCore sender timestamp.
        if timestamp < self.session_started_at - 30:
            self.log("ignored_stale_message", channel=channel, command=command)
            return
        fingerprint = message_fingerprint(channel, timestamp, text)
        if self.config.live and self.client is None:
            self.log("reply_skipped_not_connected", channel=channel, command=command, fingerprint=fingerprint)
            return
        if self.config.reply_mode == "raw_qsl" and self.report_engine is None:
            self.log("reply_skipped_profile_unavailable", channel=channel, fingerprint=fingerprint)
            return
        try:
            claim_key = command_identity(channel, timestamp, text) if self.config.reply_mode == "raw_qsl" else fingerprint
            duplicate = self.duplicates.seen(claim_key)
        except (OSError, sqlite3.Error) as exc:
            self.log("duplicate_store_failure", channel=channel, command=command,
                     fingerprint=fingerprint, error_type=type(exc).__name__)
            return  # No safe claim: do not send or silently weaken duplicate safety.
        if duplicate:
            if (self.config.reply_mode == "raw_qsl" and self.report_engine is not None
                    and claim_key not in self._active_reports):
                self.report_engine.complete(channel, timestamp, text)
            self.log("ignored_duplicate", channel=channel, command=command, fingerprint=fingerprint)
            return
        reply = COMMAND_REPLIES[command]
        if not self.config.live:
            if self.config.reply_mode == "raw_qsl":
                engine = self.report_engine
                try:
                    prepared = engine.build(channel, timestamp, text, command, int(time.time()))
                    self.log("dry_run_report", channel=channel, command=command,
                             sender_alias=prepared.sender_alias, rx_evidence_status=prepared.evidence_status,
                             body_bytes=len(prepared.body.encode("utf-8")), packet_bytes=len(prepared.packet))
                except (ValueError, UnicodeError) as exc:
                    self.log("report_preparation_failed", error_type=type(exc).__name__)
                finally:
                    engine.complete(channel, timestamp, text)
                return
            self.log("dry_run_reply", channel=channel, command=command, reply=reply)
            return
        if self.config.reply_mode == "raw_qsl":
            self._active_reports.add(claim_key)
            try:
                await self.send_report(channel, timestamp, text, command, fingerprint)
            finally:
                self._active_reports.discard(claim_key)
            return
        self.log("reply_requested", channel=channel, command=command, fingerprint=fingerprint)
        try:
            async with self._send_lock:
                response = await self.client.commands.send_chan_msg(channel, reply)
        except Exception as exc:
            self.log("reply_failed", channel=channel, command=command, fingerprint=fingerprint, error_type=type(exc).__name__)
            return
        if response is None or response.type == EventType.ERROR:
            reason = getattr(response, "payload", {"reason": "no_response"})
            self.log("reply_rejected_by_local_m1", channel=channel, command=command, fingerprint=fingerprint, reason=reason)
            return
        self.log("reply_accepted_by_local_m1", channel=channel, command=command, fingerprint=fingerprint)

    async def run_session(self, stop_requested: asyncio.Event) -> str:
        disconnected = asyncio.Event()
        client = MeshCore(
            TCPConnection(self.config.host, self.config.port),
            default_timeout=8,
            # Raw profile belongs to one physical TCP session. Only the
            # outer owner may rebuild it after a disconnect; legacy unchanged.
            auto_reconnect=self.config.reply_mode != "raw_qsl",
            max_reconnect_attempts=3,
        )
        self.client = client
        session_token = object()
        self._session_token = session_token

        async def on_channel(event: Any):
            await self.handle_channel_message(event, session_token=session_token)

        def on_raw(event: Any):
            if self._session_token is session_token and self.client is client:
                self.observe_raw_reception(event)

        async def on_disconnected(event: Any) -> None:
            payload = getattr(event, "payload", {})
            self.log("transport_disconnected", details=payload)
            disconnected.set()

        def on_raw_disconnected(event: Any) -> None:
            if self._session_token is session_token:
                self._session_token = object()
                self.report_engine = None
            self.log("transport_disconnected", error_type="SessionEnded")
            disconnected.set()

        client.subscribe(EventType.CHANNEL_MSG_RECV, on_channel)
        client.subscribe(EventType.CONTACT_MSG_RECV, self.observe_contact_message)
        client.subscribe(EventType.MESSAGES_WAITING, self.observe_messages_waiting)
        client.subscribe(EventType.DISCONNECTED, on_raw_disconnected if self.config.reply_mode == "raw_qsl" else on_disconnected)
        if self.config.reply_mode == "raw_qsl":
            client.subscribe(EventType.RX_LOG_DATA, on_raw)
        tasks = set()
        fetcher = None
        try:
            connected = await client.connect()
            if connected is None or connected.type == EventType.ERROR:
                raise ConnectionError("M1 rejected APP_START")
            if self.config.reply_mode == "raw_qsl":
                self.report_engine = await read_report_engine(client, self.config.channels, connected)
                self.log("report_profile_ready", reply_mode="raw_qsl", scope_policy="stored_default_no_override_write")
            if self.config.inbox_owner == "dashboard-api":
                pass  # one installation-wide GET owner; consume only fanout
            elif self.config.reply_mode == "raw_qsl":
                fetcher = InboxFetcher(client)
                fetch_task = await fetcher.start()
            else:
                await client.start_auto_message_fetching()
            self.log(
                "connected",
                host=self.config.host,
                port=self.config.port,
                channels=sorted(self.config.channels),
                mode="live" if self.config.live else "dry_run",
                pid=os.getpid(),
                reply_mode=self.config.reply_mode,
                inbox_owner=self.config.inbox_owner,
            )
            stop_task = asyncio.create_task(stop_requested.wait())
            disconnected_task = asyncio.create_task(disconnected.wait())
            tasks = {stop_task, disconnected_task}
            if fetcher is not None:
                tasks.add(fetch_task)
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if fetcher is not None and fetch_task in done and not stop_task.done():
                await fetch_task  # propagate actual GET failure, never silently stop fetching
                raise ConnectionError("Inbox reader ended unexpectedly")
            return "stopped" if stop_task in done else "reconnect_exhausted"
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            try:
                try:
                    if fetcher is not None:
                        await fetcher.stop()
                    elif self.config.inbox_owner == "bot":
                        await client.stop_auto_message_fetching()
                except Exception as exc:
                    self.log("cleanup_failed", stage="stop_fetch", error_type=type(exc).__name__)
                try:
                    await client.disconnect()
                except Exception as exc:
                    self.log("cleanup_failed", stage="disconnect", error_type=type(exc).__name__)
                    # SDK disconnect itself repeats fetch cleanup. If that
                    # fails, still close the underlying transport independently.
                    transport = getattr(getattr(client, "connection_manager", None), "connection", None)
                    if transport is not None:
                        await transport.disconnect()
            finally:
                self.client = None
                self.report_engine = None
                self._session_token = object()

    async def run_forever(self, stop_requested: asyncio.Event) -> None:
        delay = 1.0
        while not stop_requested.is_set():
            try:
                reason = await self.run_session(stop_requested)
                if reason == "stopped":
                    break
                self.log("session_restart", delay_seconds=delay, reason=reason)
            except Exception as exc:
                self.log("session_failure", error_type=type(exc).__name__, error=str(exc), delay_seconds=delay)
            try:
                await asyncio.wait_for(stop_requested.wait(), timeout=delay)
            except asyncio.TimeoutError:
                delay = min(delay * 2, 30.0)
            else:
                break
        self.log("stopped")


def configure_logging(log_file: Path) -> logging.Logger:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("meshcore.room_bot")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    return logger


async def async_main(live: bool) -> int:
    config = BotConfig.from_environment(live=live)
    logger = configure_logging(config.log_file)
    stop_requested = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stop_requested.set)
        except NotImplementedError:  # Windows console fallback
            pass
    bot = RoomBot(config, logger)
    with ExitStack() as ownership:
        try:
            # Validate/init and hold ownership before any SDK connection or
            # command claim. Legacy/non-sending dry runs do not use this store.
            owner = reply_history_writer(config.history_path) if live and config.reply_mode == "raw_qsl" else nullcontext()
            ownership.enter_context(owner)
        except InstanceAlreadyRunningError:
            bot.log("reply_history_owner_unavailable", error_type="InstanceAlreadyRunningError")
            return 2
        except (OSError, sqlite3.Error, ValueError) as exc:
            bot.log("reply_history_initialization_failed", error_type=type(exc).__name__,
                    sqlite_errorcode=getattr(exc, "sqlite_errorcode", None),
                    sqlite_errorname=getattr(exc, "sqlite_errorname", None))
            return 3
        try:
            await bot.run_forever(stop_requested)
        except KeyboardInterrupt:
            stop_requested.set()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Allow RF-bound replies. Without this option the process is a dry run.",
    )
    args = parser.parse_args()
    # Hold an OS file lock for the lifetime of the bot. Closing/crashing the
    # process releases the lock, unlike a stale PID file.
    runtime = Path(__file__).parent / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    try:
        with hold_instance_lock(runtime / "room-bot.lock"):
            return asyncio.run(async_main(live=args.live))
    except InstanceAlreadyRunningError:
        print("Bot already running", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
