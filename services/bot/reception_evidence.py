"""Isolated, fail-closed local RX evidence; deliberately NOT wired into the bot.

Supported profile: firmware d929643 flood GRP_TXT, version 0, flags 0,
strict UTF-8 and canonical C-string text/minimal AES zero padding. Sources:
https://github.com/meshcore-dev/MeshCore/blob/d929643/src/helpers/BaseChatMesh.cpp#L442
https://github.com/meshcore-dev/MeshCore/blob/d929643/src/Utils.cpp#L117
https://github.com/meshcore-dev/MeshCore/blob/d929643/examples/companion_radio/MyMesh.cpp#L266

No clocks, SDK clients, files, logs, sends or new dependencies. Keys and text
remain only in bounded private memory. Channel MAC authenticates the channel,
NOT the displayed sender name or the unverified repeater-prefix path.
"""
from __future__ import annotations

import hashlib
import hmac
from collections import deque
from dataclasses import dataclass, field
from typing import Mapping

from Crypto.Cipher import AES
from Crypto.Hash import HMAC, SHA256


MAX_PUSH_BYTES = 176  # d929643 BaseSerialInterface.h: complete companion frame
MAX_PATH_BYTES = 64
MAX_PAYLOAD_BYTES = 184
MAX_TEXT_BYTES = 160  # BaseChatMesh.h; boundary may be sender-truncated


@dataclass(frozen=True)
class ReceptionCopy:
    channel_index: int
    sender_timestamp: int
    text_bytes: bytes = field(repr=False)
    snr_db: float
    rssi_dbm: int
    hops: int
    path_hashes: tuple[str, ...]
    payload_identity: str  # full SHA256(type || payload), NOT SDK's 32-bit hash


@dataclass(frozen=True)
class EvidenceResult:
    status: str
    reason: str
    copies: tuple[ReceptionCopy, ...] = ()


@dataclass(frozen=True)
class PathHop:
    hash_hex: str
    status: str
    name: str | None = None
    candidates: int = 0


def _unavailable(reason: str) -> EvidenceResult:
    # Fixed diagnostic codes only: never exceptions, channel keys or chat text.
    return EvidenceResult("unavailable", reason)


def _text_bytes(text: str | bytes) -> bytes | None:
    try:
        raw = text.encode("utf-8", "strict") if isinstance(text, str) else text
        if not isinstance(raw, bytes) or not raw or b"\0" in raw or len(raw) >= MAX_TEXT_BYTES:
            return None
        decoded = raw.decode("utf-8", "strict")
        # The firmware's supported sender profile is exactly '<name>: <body>'.
        name, separator, body = decoded.partition(": ")
        if not separator or not name or not body or len(name.encode("utf-8")) > 31:
            return None
        return raw
    except (UnicodeError, TypeError):
        return None


class ReceptionEvidence:
    """Keeps whole RX copies, never blends metadata or guesses from timing.

    Each input is one complete 0x88 push payload, including SNR/RSSI. Feed a
    single raw-RX source; this is not a count of unique repeaters or a detector
    of transport fan-out. Clear explicitly when switching source/session/keys.
    After any storage eviction, matching is unavailable until explicit clear:
    losing an earlier copy cannot prove that a retained copy was unique.
    """

    def __init__(self, channels: Mapping[int, bytes], max_copies: int = 128):
        if type(max_copies) is not int or not 1 <= max_copies <= 1024:
            raise ValueError("Invalid evidence capacity")
        if not isinstance(channels, Mapping) or len(channels) > 256:
            raise ValueError("Invalid channel configuration")
        self._channels: dict[int, bytes] = {}
        for index, secret in channels.items():
            if type(index) is not int or not 0 <= index <= 255 or not isinstance(secret, bytes) or len(secret) != 16:
                raise ValueError("Invalid channel configuration")
            self._channels[index] = secret
        self._copies: deque[ReceptionCopy] = deque(maxlen=max_copies)
        self._coverage_lost = False

    @property
    def copy_count(self) -> int:
        return len(self._copies)

    def clear(self) -> None:
        self._copies.clear()
        self._coverage_lost = False

    def observe(self, push: bytes) -> EvidenceResult:
        if not isinstance(push, bytes) or not 5 <= len(push) <= MAX_PUSH_BYTES or push[0] != 0x88:
            return _unavailable("frame_bounds")
        raw = push[3:]
        header = raw[0]
        version, payload_type, route = header >> 6, (header >> 2) & 15, header & 3
        if version != 0 or payload_type != 5 or route not in (0, 1):
            return _unavailable("unsupported_profile")
        offset = 5 if route == 0 else 1  # transport flood has four scope bytes
        if len(raw) <= offset:
            return _unavailable("transport_bounds")
        descriptor = raw[offset]
        offset += 1
        mode, hops = descriptor >> 6, descriptor & 63
        width = mode + 1
        path_size = hops * width
        if mode == 3 or path_size > MAX_PATH_BYTES or offset + path_size > len(raw):
            return _unavailable("path_bounds")
        path = raw[offset:offset + path_size]
        payload = raw[offset + path_size:]
        if not 19 <= len(payload) <= MAX_PAYLOAD_BYTES or (len(payload) - 3) % 16:
            return _unavailable("cipher_bounds")
        channel_hash, mac, crypted = payload[:1], payload[1:3], payload[3:]
        candidates = []
        for index, secret in self._channels.items():
            if hashlib.sha256(secret).digest()[:1] != channel_hash:
                continue
            # Official SDK uses 16-byte PSK. Firmware's 32-byte group secret
            # zero-extends that PSK; HMAC block padding makes these equivalent.
            digest = HMAC.new(secret, crypted, digestmod=SHA256).digest()[:2]
            if hmac.compare_digest(digest, mac):
                candidates.append((index, secret))
        if not candidates:
            return _unavailable("unknown_channel_or_mac")
        if len(candidates) != 1:
            return EvidenceResult("ambiguous", "channel_not_unique")
        index, secret = candidates[0]
        plain = AES.new(secret, AES.MODE_ECB).decrypt(crypted)
        if len(plain) < 5 or plain[4] != 0:
            return _unavailable("unsupported_flags")
        text_and_padding = plain[5:]
        split = text_and_padding.find(b"\0")
        if split == -1:
            text = text_and_padding
        else:
            text, padding = text_and_padding[:split], text_and_padding[split:]
            if len(padding) >= 16 or any(padding):
                return _unavailable("noncanonical_nul_or_padding")
        # A trailing literal NUL is indistinguishable from padding on the wire.
        # Only canonical firmware-visible C-string text is claimed. NUL-bearing
        # caller text is always rejected by match(), never normalized away.
        text = _text_bytes(text)
        if text is None:
            return _unavailable("invalid_or_truncated_text")
        expected_size = ((5 + len(text) + 15) // 16) * 16
        if expected_size != len(plain):
            return _unavailable("noncanonical_padding")
        copy = ReceptionCopy(
            index, int.from_bytes(plain[:4], "little"), text,
            int.from_bytes(push[1:2], "little", signed=True) / 4,
            int.from_bytes(push[2:3], "little", signed=True), hops,
            tuple(path[i:i + width].hex() for i in range(0, path_size, width)),
            hashlib.sha256(bytes([payload_type]) + payload).hexdigest(),
        )
        if len(self._copies) == self._copies.maxlen:
            self._coverage_lost = True
        self._copies.append(copy)
        return EvidenceResult("available", "validated_local_rx_copy", (copy,))

    def match(self, channel: int, timestamp: int, text: str | bytes) -> EvidenceResult:
        raw = _text_bytes(text)
        if (type(channel) is not int or channel not in self._channels or type(timestamp) is not int
                or not 0 <= timestamp <= 0xFFFFFFFF or raw is None):
            return _unavailable("invalid_match_key")
        if self._coverage_lost:
            return _unavailable("reception_coverage_lost")
        copies = tuple(copy for copy in self._copies if copy.channel_index == channel
                       and copy.sender_timestamp == timestamp and copy.text_bytes == raw)
        if not copies:
            return _unavailable("no_exact_reception")
        if len(copies) != 1:
            return EvidenceResult("ambiguous", "multiple_rx_copies", copies)
        return EvidenceResult("available", "exact_local_rx_copy", copies)


def resolve_path(copy: ReceptionCopy, contacts: Mapping[str, str]) -> tuple[PathHop, ...]:
    """Resolve only unique full public-key prefixes; no default node names.

    Prefixes in a flood path are not signed identities. 'resolved' means only
    one candidate in this contact snapshot, not authenticated RF attribution.
    """
    known = {}
    for key, name in contacts.items():
        if (not isinstance(key, str) or len(key) != 64 or not isinstance(name, str)
                or any(char not in "0123456789abcdefABCDEF" for char in key)):
            continue
        try:
            if len(bytes.fromhex(key)) != 32:
                continue
        except ValueError:
            continue
        known[key.lower()] = name
    result = []
    for prefix in copy.path_hashes:
        candidates = [name for key, name in known.items() if key.startswith(prefix)]
        if len(candidates) == 1:
            result.append(PathHop(prefix, "resolved", candidates[0], 1))
        else:
            result.append(PathHop(prefix, "ambiguous" if candidates else "unknown", candidates=len(candidates)))
    return tuple(result)


def format_qsl(result: EvidenceResult, max_utf8_bytes: int = 139) -> str | None:
    """Privacy-safe text: no chat, channel key, guessed names or return metrics.

    Budget is for this returned text only; a later sender prefix consumes its
    own bytes. No slicing inside UTF-8 or truncating away the local-RX label.
    """
    if type(max_utf8_bytes) is not int or not 0 <= max_utf8_bytes <= 160:
        raise ValueError("Invalid QSL byte budget")
    if result.status == "available" and len(result.copies) == 1:
        copy = result.copies[0]
        last = copy.path_hashes[-1] if copy.path_hashes else "kein Relay"
        metrics = f"{copy.hops}H SNR{copy.snr_db:+g}dB RSSI{copy.rssi_dbm}dBm"
        choices = (f"QSL RX lokal: {metrics}; letzter Hash {last}; Rueckweg unbekannt",
                   f"QSL RX lokal: {metrics}; Rueckweg unbekannt")
    else:
        state = "mehrdeutig" if result.status == "ambiguous" else "unbekannt"
        choices = (f"QSL RX lokal: {state}; Rueckweg unbekannt",)
    return next((text for text in choices if len(text.encode("utf-8")) <= max_utf8_bytes), None)
