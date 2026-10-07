"""Strict group-text encoder for firmware1.17.1-d929643 CMD65.

Channel display alias only: NOT another public-key node identity.
No SDK clients, sends, files, settings, or scope/key discovery here.
Sources: pinned BaseChatMesh.cpp, Utils.cpp, Packet.cpp, TransportKeyStore.cpp.
Caller must supply the independently established outbound flood profile;
unknown scope is NOT represented by FloodProfile(..., None).
"""
from dataclasses import dataclass, field
import hashlib
import hmac
import struct

from Crypto.Cipher import AES


@dataclass(frozen=True)
class FloodProfile:
    path_hash_mode: int
    scope_key: bytes | None = field(repr=False)

    def __post_init__(self):
        if type(self.path_hash_mode) is not int or self.path_hash_mode not in (0, 1, 2):
            raise ValueError("Invalid path mode")
        if self.scope_key is not None and (
            not isinstance(self.scope_key, bytes) or len(self.scope_key) != 16 or not any(self.scope_key)
        ):
            raise ValueError("Invalid scope key")


def group_packet(channel_key: bytes, alias: str, body: str, timestamp: int,
                 profile: FloodProfile) -> bytes:
    if not isinstance(channel_key, bytes) or len(channel_key) != 16:
        raise ValueError("Invalid channel key")
    if not isinstance(profile, FloodProfile):
        raise ValueError("Unknown outbound profile")
    if type(timestamp) is not int or not 0 <= timestamp <= 0xffffffff:
        raise ValueError("Invalid timestamp")
    if not isinstance(alias, str) or not alias or any(ord(c) < 32 or c == ":" for c in alias):
        raise ValueError("Invalid sender alias")
    if not isinstance(body, str) or not body or "\0" in body:
        raise ValueError("Invalid message body")
    try:
        name = alias.encode("utf-8", "strict")
        text = (alias + ": " + body).encode("utf-8", "strict")
    except UnicodeError:
        raise ValueError("Invalid UTF-8") from None
    if len(name) > 31 or len(text) > 155:
        raise ValueError("Message byte budget exceeded")
    plain = struct.pack("<I", timestamp) + b"\0" + text
    padded = plain + bytes(-len(plain) % 16)
    cipher = AES.new(channel_key, AES.MODE_ECB).encrypt(padded)
    mac = hmac.new(channel_key, cipher, hashlib.sha256).digest()[:2]
    payload = hashlib.sha256(channel_key).digest()[:1] + mac + cipher
    descriptor = bytes([profile.path_hash_mode << 6])  # no invented outbound relay path
    if profile.scope_key is None:
        packet = b"\x15" + descriptor + payload
    else:
        code = int.from_bytes(hmac.new(profile.scope_key, b"\x05" + payload, hashlib.sha256).digest()[:2], "little")
        code = 1 if code == 0 else 0xfffe if code == 0xffff else code
        packet = b"\x14" + struct.pack("<HH", code, 0) + descriptor + payload
    if len(packet) + 2 > 176:
        raise ValueError("Companion frame budget exceeded")
    return packet
