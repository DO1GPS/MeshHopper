"""Bounded command-only correlation and channel-sender packet preparation.

No socket, SDK, radio send or persisted secret. A prepared packet is not a
delivery proof. Lost copies remain unavailable, never a guessed unique RX.
"""
from collections import OrderedDict
from dataclasses import dataclass, field
import hashlib
import time

from bot_report import response_body
from bot_identity import BOT_NAME, BOT_BODY_BUDGET
from bot_commands import parse_command
from group_sender import FloodProfile, group_packet
from reception_evidence import EvidenceResult, ReceptionEvidence


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
                 *, clock=time.monotonic, max_pending=128):
        if type(max_pending) is not int or not 1 <= max_pending <= 1024:
            raise ValueError("Invalid pending capacity")
        if not isinstance(profile, FloodProfile):
            raise ValueError("Unknown outbound profile")
        if (profile.scope_key is None) != (scope_name is None):
            raise ValueError("Scope label and key disagree")
        self._channels = dict(channels)
        ReceptionEvidence(self._channels)  # validate keys even before first RX
        self._profile, self._scope_name = profile, scope_name
        self._contacts = dict(contacts)
        self._clock, self._max_pending = clock, max_pending
        self._pending = OrderedDict()
        self._done = OrderedDict()
        self._lost = OrderedDict()
        self._coverage_lost = False

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
        if _command(text) not in ("ping", "test", "room", "thanks"):
            return EvidenceResult("unavailable", "not_a_command")
        key = _key(copy.channel_index, copy.sender_timestamp, text)
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

    def build(self, channel, sender_timestamp, original_text, command, response_timestamp):
        self._expire()
        key = _key(channel, sender_timestamp, original_text)
        if channel not in self._channels or command != _command(original_text):
            raise ValueError("Reply does not match command")
        copies = self._pending.get(key, ())
        if self._coverage_lost or key in self._lost or key in self._done or not copies:
            evidence = EvidenceResult("unavailable", "no_complete_exact_reception")
        elif len(copies) != 1:
            evidence = EvidenceResult("ambiguous", "multiple_rx_copies", copies)
        else:
            evidence = EvidenceResult("available", "exact_local_rx_copy", copies)
        identity = key.hex()
        sender = original_text.partition(": ")[0]
        body = response_body(command, evidence, self._contacts, self._scope_name,
                             budget=BOT_BODY_BUDGET,
                             original_sender=sender, request_tag=identity[:16])
        alias = BOT_NAME
        packet = group_packet(self._channels[channel], alias, body, response_timestamp, self._profile)
        return PreparedReply(channel, response_timestamp, alias, body, packet, evidence.status, identity)

    def complete(self, channel, sender_timestamp, original_text):
        now = self._expire()
        key = _key(channel, sender_timestamp, original_text)
        self._pending.pop(key, None)
        self._remember(self._done, key, now, 2048)
