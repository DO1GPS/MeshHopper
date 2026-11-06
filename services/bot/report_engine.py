"""Bounded command-only correlation and channel-sender packet preparation.

No socket, SDK, radio send or persisted secret. A prepared packet is not a
delivery proof. Lost copies remain unavailable, never a guessed unique RX.
"""
from collections import OrderedDict
from dataclasses import dataclass, field, replace
import hashlib
import time

from bot_report import response_body, path_response_bodies, room_response_body
from bot_identity import BOT_NAME, BOT_BODY_BUDGET
from bot_commands import parse_command
from group_sender import FloodProfile, group_packet
from reception_evidence import EvidenceResult, InboxMetrics, ReceptionEvidence


def _command(text):
    return parse_command(text, wire=True)


def _key(channel, timestamp, text):
    if (type(channel) is not int or not 0 <= channel <= 255 or
            type(timestamp) is not int or not 0 <= timestamp <= 0xffffffff or
            not isinstance(text, str) or "\0" in text):
        raise ValueError("Invalid correlation key")
    return hashlib.sha256(bytes([channel]) + timestamp.to_bytes(4, "little") +
                          text.encode("utf-8", "strict")).digest()


def command_identity(channel, timestamp, text):
    """Full private correlation digest, not the shortened display fingerprint."""
    return _key(channel, timestamp, text).hex()


@dataclass(frozen=True)
class PreparedReply:
    channel: int
    timestamp: int
    sender_alias: str
    body: str = field(repr=False)
    packet: bytes = field(repr=False)
    evidence_status: str
    request_identity: str
    part_index: int | None = None
    part_total: int | None = None
    rx_metrics_source: str = "none"

    @property
    def packet_identity(self):
        """Firmware Packet::calculateHash input: type + payload, not scope/path."""
        if not isinstance(self.packet, bytes) or not self.packet or self.packet[0] not in (0x14, 0x15):
            raise ValueError("Unsupported outgoing packet")
        offset = 5 if self.packet[0] == 0x14 else 1
        if len(self.packet) < offset + 20 or self.packet[offset] & 63:
            raise ValueError("Invalid outgoing path or payload")
        return hashlib.sha256(b"\x05" + self.packet[offset + 1:]).hexdigest()


class BotReportEngine:
    def __init__(self, channels, profile: FloodProfile, scope_name, contacts,
                 *, clock=time.monotonic, max_pending=128, channel_names=None,
                 contact_catalog=None):
        if type(max_pending) is not int or not 1 <= max_pending <= 1024:
            raise ValueError("Invalid pending capacity")
        if not isinstance(profile, FloodProfile):
            raise ValueError("Unknown outbound profile")
        if (profile.scope_key is None) != (scope_name is None):
            raise ValueError("Scope label and key disagree")
        self._channels = dict(channels)
        ReceptionEvidence(self._channels)  # validate keys even before first RX
        if channel_names is not None and (not isinstance(channel_names, dict)
                                          or set(channel_names) != set(self._channels)):
            raise ValueError("Room names do not match configured Bot channels")
        self._channel_names = None if channel_names is None else dict(channel_names)
        self._profile, self._scope_name = profile, scope_name
        self._contacts = dict(contacts)
        self._contact_catalog = contact_catalog
        self._clock, self._max_pending = clock, max_pending
        self._pending = OrderedDict()
        self._done = OrderedDict()
        self._lost = OrderedDict()
        self._coverage_lost = False
        # One accepted Ping/Test per configured channel, only for this device
        # session. Keep whole RX copies independently of command completion.
        self._last_probes = {}

    @staticmethod
    def _copy_evidence(copies):
        if not copies:
            return EvidenceResult("unavailable", "no_complete_exact_reception")
        if len(copies) != 1:
            return EvidenceResult("ambiguous", "multiple_rx_copies", copies)
        return EvidenceResult("available", "exact_local_rx_copy", copies)

    def remember_probe(self, channel, sender_timestamp, original_text):
        """Called once after fresh Inbox admission, before any send wait.

        Arrival order, not the remote sender's clock, defines 'last'. Raw
        reception alone must not select a target (it may be old or a copy).
        """
        key = _key(channel, sender_timestamp, original_text)
        if channel not in self._channels or _command(original_text) not in ("ping", "test"):
            raise ValueError("Path target must be an admitted Ping/Test")
        previous = self._last_probes.get(channel)
        if previous is not None and previous[0] == key:
            return
        copies = self._pending.get(key, ())
        evidence = (EvidenceResult("unavailable", "no_complete_exact_reception")
                    if self._coverage_lost or key in self._lost or key in self._done else
                    self._copy_evidence(copies))
        # A missing new path replaces the old target too. Store bounded display
        # metadata, not a second unbounded collection of whole message texts.
        sender = original_text.partition(": ")[0]
        sender = sender.encode("utf-8", "strict")[:31].decode("utf-8", "ignore")
        self._last_probes[channel] = (key, sender, evidence)

    def _expire(self):
        now = self._clock()
        for records in (self._done,):
            for key in tuple(records):
                if records[key] <= now:
                    del records[key]
        return now

    def _remember(self, records, key, now, limit):
        records[key] = now + 600
        if len(records) > limit:
            records.popitem(last=False)
            # Once a tombstone is lost, uniqueness cannot be asserted again
            # during this engine session. Sending policy is a separate owner.
            self._coverage_lost = True

    @property
    def pending_count(self):
        return len(self._pending)

    @property
    def done_count(self):
        self._expire()
        return len(self._done)

    def observe(self, push: bytes):
        now = self._expire()
        # Parse one copy without the diagnostic helper's permanent global
        # eviction state. This engine owns command-specific loss accounting.
        result = ReceptionEvidence(self._channels, max_copies=1).observe(push)
        if result.status != "available":
            return result
        copy = result.copies[0]
        text = copy.text_bytes.decode("utf-8", "strict")
        if _command(text) not in ("ping", "test", "room", "thanks", "path", "help"):
            return EvidenceResult("unavailable", "not_a_command")
        key = _key(copy.channel_index, copy.sender_timestamp, text)
        latest = self._last_probes.get(copy.channel_index)
        if (latest is not None and latest[0] == key and not self._coverage_lost
                and key not in self._lost):
            # Raw can follow the Inbox event, even after its reply completed.
            # Exact identity only; never borrow a nearby message or new Ping.
            copies = (latest[2].copies + (copy,))[:2]
            self._last_probes[copy.channel_index] = (key, latest[1], self._copy_evidence(copies))
        if self._coverage_lost or key in self._done or key in self._lost:
            return EvidenceResult("unavailable", "completed_or_lost_reception")
        if key in self._pending:
            # Two copies are sufficient to prove ambiguity, regardless of
            # identical path/metrics; do not count these as unique repeaters.
            self._pending[key] = (self._pending[key] + (copy,))[:2]
        else:
            if len(self._pending) == self._max_pending:
                lost_key, _ = self._pending.popitem(last=False)
                self._remember(self._lost, lost_key, now, 1024)
            self._pending[key] = (copy,)
        return result

    def build(self, channel, sender_timestamp, original_text, command, response_timestamp,
              *, inbox_metrics=None):
        self._expire()
        key = _key(channel, sender_timestamp, original_text)
        if channel not in self._channels or command != _command(original_text):
            raise ValueError("Reply does not match command")
        if inbox_metrics is not None and (not isinstance(inbox_metrics, InboxMetrics)
                or _key(inbox_metrics.channel_index, inbox_metrics.sender_timestamp,
                        inbox_metrics.text_bytes.decode("utf-8", "strict")) != key):
            raise ValueError("Inbox metrics do not match request")
        copies = self._pending.get(key, ())
        if self._coverage_lost or key in self._lost or key in self._done or not copies:
            evidence = EvidenceResult("unavailable", "no_complete_exact_reception")
        elif len(copies) != 1:
            evidence = EvidenceResult("ambiguous", "multiple_rx_copies", copies)
        else:
            evidence = EvidenceResult("available", "exact_local_rx_copy", copies)
        identity = key.hex()
        sender = original_text.partition(": ")[0]
        contacts = (self._contacts if self._contact_catalog is None else
                    self._contact_catalog.snapshot())
        body = (room_response_body(channel, self._channel_names, BOT_BODY_BUDGET)
                if command == "room" and self._channel_names is not None else
                response_body(command, evidence, contacts, self._scope_name,
                              budget=BOT_BODY_BUDGET,
                              original_sender=sender, request_tag=identity[:16],
                              inbox_metrics=inbox_metrics))
        alias = BOT_NAME
        packet = group_packet(self._channels[channel], alias, body, response_timestamp, self._profile)
        metrics_source = ("raw_copy" if evidence.status in {"available", "ambiguous"} else
                          "inbox_v3" if inbox_metrics is not None else "none") if command in {"ping", "test"} else "none"
        return PreparedReply(channel, response_timestamp, alias, body, packet, evidence.status, identity,
                             rx_metrics_source=metrics_source)

    def complete(self, channel, sender_timestamp, original_text):
        now = self._expire()
        key = _key(channel, sender_timestamp, original_text)
        self._pending.pop(key, None)
        self._remember(self._done, key, now, 2048)

    def build_path(self, channel, sender_timestamp, original_text, response_timestamp):
        """Freeze the channel's last admitted Ping/Test, not PFAD's own RX."""
        self._expire()
        key = _key(channel, sender_timestamp, original_text)
        if channel not in self._channels or _command(original_text) != "path":
            raise ValueError("Reply does not match path command")
        latest = self._last_probes.get(channel)
        if (self._coverage_lost or key in self._lost or key in self._done
                or latest is not None and latest[0] in self._lost):
            evidence = EvidenceResult("unavailable", "no_complete_exact_reception")
        else:
            evidence = latest[2] if latest is not None else EvidenceResult("unavailable", "no_channel_probe")
        contacts = (self._contacts if self._contact_catalog is None else
                    self._contact_catalog.snapshot())
        bodies = (path_response_bodies(evidence, contacts, max_bytes=BOT_BODY_BUDGET,
                                      original_sender=latest[1] if latest is not None else None)
                  if latest is not None else ("📩 Noch kein Ping/Test in diesem Kanal",))
        return tuple(PreparedReply(channel, response_timestamp, BOT_NAME, body,
                    group_packet(self._channels[channel], BOT_NAME, body, response_timestamp, self._profile),
                    evidence.status, key.hex(), index, len(bodies))
                    for index, body in enumerate(bodies, 1))

    def retime_path(self, replies, response_timestamp):
        """Re-encode a frozen series at an actual clock reading; no new RX."""
        if (not isinstance(replies, tuple) or not 1 <= len(replies) <= 63
                or any(not isinstance(reply, PreparedReply) or reply.channel not in self._channels
                       or reply.sender_alias != BOT_NAME or type(reply.part_index) is not int
                       or reply.part_index != index or type(reply.part_total) is not int
                       or reply.part_total != len(replies)
                       or reply.request_identity != replies[0].request_identity
                       or reply.channel != replies[0].channel
                       for index, reply in enumerate(replies, 1))):
            raise ValueError("Invalid frozen path series")
        return tuple(replace(reply, timestamp=response_timestamp,
                    packet=group_packet(self._channels[reply.channel], reply.sender_alias,
                                        reply.body, response_timestamp, self._profile)) for reply in replies)
