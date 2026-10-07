"""Small, synthetic public-core gate; no SDK client, radio, database or socket.

Test dependencies: Python 3.11/3.12, unittest (stdlib), pycryptodome==3.23.0.
The full bot additionally needs meshcore==2.3.14 and its installed dependencies:
bleak, pycayennelpp, pycryptodome, pyserial-asyncio-fast. These tests do not
prove that a real companion/transport, firmware profile or HA install works.

Public source layout, relative to this test's parent directory:
services/bot/{meshcore_room_bot,bot_identity,bot_commands,bot_report,
group_sender,reception_evidence,report_engine,report_profile,raw_reply_history}.py
services/{meshcore_inbox_fetch,meshcore_process_lock}.py

Run from the exported root:
    python -B -m unittest discover -s tests -p test_bot_public_core.py
Before export only, MESHCORE_PUBLIC_ROOT may explicitly select the source root.
There is no lookup of private SDK folders, old fixtures, logs or operator state.
All keys, times, names and packets below are invented public fixture values.
"""
from __future__ import annotations

import ast
import hashlib
import hmac
import os
from pathlib import Path
import re
import struct
import sys
import unittest

ROOT = Path(os.environ.get("MESHCORE_PUBLIC_ROOT", Path(__file__).resolve().parents[1])).resolve()
BOT_SOURCE = ROOT / "services" / "bot"
if not (BOT_SOURCE / "bot_commands.py").is_file():
    raise ImportError("Public core sources missing: run in the export or set MESHCORE_PUBLIC_ROOT")
sys.path.insert(0, str(BOT_SOURCE))

from Crypto.Cipher import AES
import bot_commands
import bot_identity
import bot_report
import group_sender
import reception_evidence
import report_engine

PUBLIC_FILES = (
    "services/bot/meshcore_room_bot.py", "services/bot/bot_identity.py",
    "services/bot/bot_commands.py", "services/bot/bot_report.py",
    "services/bot/group_sender.py", "services/bot/reception_evidence.py",
    "services/bot/report_engine.py", "services/bot/report_profile.py",
    "services/bot/raw_reply_history.py", "services/meshcore_inbox_fetch.py",
    "services/meshcore_process_lock.py",
)
KEY = bytes(range(16))
OTHER_KEY = bytes(range(16, 32))
REQUEST_TIME = 1_700_000_000
RESPONSE_TIME = REQUEST_TIME + 1
CONTACTS = {"a1" + "01" * 31: "North", "b2" + "02" * 31: "South"}


def receive_frame(text="Demo: Ping", *, timestamp=REQUEST_TIME,
                  path=(b"\xa1", b"\xb2"), snr_quarters=46, rssi=-100):
    """Independent version-0, plain-group-text fixture with one-byte hops."""
    plain = struct.pack("<I", timestamp) + b"\0" + text.encode("utf-8")
    encrypted = AES.new(KEY, AES.MODE_ECB).encrypt(plain + bytes(-len(plain) % 16))
    mac = hmac.new(KEY + bytes(16), encrypted, hashlib.sha256).digest()[:2]
    payload = hashlib.sha256(KEY).digest()[:1] + mac + encrypted
    packet = b"\x15" + bytes([len(path)]) + b"".join(path) + payload
    return bytes([0x88, snr_quarters & 255, rssi & 255]) + packet


def decode_reply(packet):
    """Check the actual packet, not merely the formatter return value."""
    offset = 5 if packet[0] == 0x14 else 1
    if packet[0] not in (0x14, 0x15) or packet[offset] & 63:
        raise AssertionError("Reply must have a supported flood header and no invented path")
    payload = packet[offset + 1:]
    if not hmac.compare_digest(payload[1:3], hmac.new(KEY, payload[3:], hashlib.sha256).digest()[:2]):
        raise AssertionError("Reply MAC mismatch")
    plain = AES.new(KEY, AES.MODE_ECB).decrypt(payload[3:])
    return int.from_bytes(plain[:4], "little"), plain[4], plain[5:].rstrip(b"\0").decode("utf-8")


class PublicCoreTests(unittest.TestCase):
    def engine(self, *, contacts=CONTACTS):
        return report_engine.BotReportEngine(
            {2: KEY}, group_sender.FloodProfile(0, OTHER_KEY), "lab", contacts,
        )

    def assert_public_body(self, reply, head):
        self.assertTrue(reply.body.startswith(head + " @Demo\n"))
        self.assertNotIn("RSSI", reply.body)
        self.assertIsNone(re.search(r"#[0-9a-fA-F]{16}", reply.body))
        self.assertIn("TX lab | Rückweg offen", reply.body)
        self.assertLessEqual(len(reply.body.encode("utf-8")), bot_identity.BOT_BODY_BUDGET)
        self.assertLessEqual(len((reply.sender_alias + ": " + reply.body).encode("utf-8")), 155)
        self.assertLessEqual(len(reply.packet) + 2, 176)
        timestamp, text_type, text = decode_reply(reply.packet)
        self.assertEqual(timestamp, RESPONSE_TIME)
        self.assertEqual(text_type, 0)
        self.assertEqual(text, reply.sender_alias + ": " + reply.body)

    def test_all_eleven_source_files_have_only_known_local_or_external_imports(self):
        local_names = {Path(name).stem for name in PUBLIC_FILES}
        allowed = sys.stdlib_module_names | local_names | {"meshcore", "Crypto"}
        for name in PUBLIC_FILES:
            with self.subTest(source=name):
                source = ROOT / name
                self.assertTrue(source.is_file())
                for node in ast.walk(ast.parse(source.read_text(encoding="utf-8-sig"))):
                    if isinstance(node, ast.Import):
                        imported = [item.name.split(".", 1)[0] for item in node.names]
                    elif isinstance(node, ast.ImportFrom):
                        self.assertEqual(node.level, 0, "Unlisted relative dependency")
                        imported = [node.module.split(".", 1)[0]] if node.module else []
                    else:
                        continue
                    self.assertTrue(set(imported) <= allowed, imported)

    def test_loaded_core_modules_come_only_from_the_selected_public_source(self):
        for module in (bot_commands, bot_identity, bot_report, group_sender,
                       reception_evidence, report_engine):
            with self.subTest(module=module.__name__):
                self.assertEqual(Path(module.__file__).resolve().parent, BOT_SOURCE)

    def test_complete_ascii_commands_produce_one_canonical_family(self):
        cases = {"ping": "ping", "PING": "ping", "reping": "ping",
                 "test": "test", "ReTest": "test", "room": "room",
                 "ROOM": "room", "ping test": "test", "test ping": "test",
                 "reping retest": "test", "ping 123": "ping", "retest 654321": "test"}
        for text, command in cases.items():
            with self.subTest(text=text):
                self.assertEqual(bot_commands.parse_command(text), command)
                self.assertEqual(bot_commands.parse_command("Demo: " + text, wire=True), command)

    def test_sentence_unicode_lookalike_and_embedded_control_do_not_trigger(self):
        for text in ("please ping me", "ping ping", "room test", "ping 1234567",
                     "PİNG", "ＰＩＮＧ", "ping\n test", "pi\0ng", "Demo: ping", None, 1):
            with self.subTest(text=text):
                self.assertIsNone(bot_commands.parse_command(text))

    def test_ping_test_room_real_packet_roundtrip_hare_snr_no_rssi_or_hex_line(self):
        for command, head in (("ping", "PONG"), ("test", "TEST"), ("room", "ROOM")):
            with self.subTest(command=command):
                engine = self.engine()
                text = "Demo: " + command
                observed = engine.observe(receive_frame(text))
                self.assertEqual(observed.status, "available")
                reply = engine.build(2, REQUEST_TIME, text, command, RESPONSE_TIME)
                self.assert_public_body(reply, head)
                self.assertEqual(reply.sender_alias, bot_identity.BOT_NAME)
                self.assertEqual(reply.body.splitlines(), [head + " @Demo", "RX 2 🐇 | SNR +11.5 dB",
                                                          "Weg: North>South", "TX lab | Rückweg offen"])
                self.assertEqual(observed.copies[0].rssi_dbm, -100)
                self.assertEqual(reply.request_identity, report_engine.command_identity(2, REQUEST_TIME, text))

    def test_zero_hops_snr_and_rssi_are_real_values_not_missing(self):
        engine = self.engine()
        observed = engine.observe(receive_frame(path=(), snr_quarters=0, rssi=0))
        reply = engine.build(2, REQUEST_TIME, "Demo: Ping", "ping", RESPONSE_TIME)
        self.assert_public_body(reply, "PONG")
        self.assertIn("RX 0 🐇 | SNR +0 dB\nWeg: direkt", reply.body)
        self.assertEqual((observed.copies[0].hops, observed.copies[0].snr_db, observed.copies[0].rssi_dbm), (0, 0.0, 0))

    def test_evidence_match_requires_channel_timestamp_and_original_text(self):
        evidence = reception_evidence.ReceptionEvidence({2: KEY, 5: OTHER_KEY})
        evidence.observe(receive_frame())
        self.assertEqual(evidence.match(2, REQUEST_TIME, "Demo: Ping").status, "available")
        for channel, timestamp, text in ((5, REQUEST_TIME, "Demo: Ping"),
                                         (2, REQUEST_TIME + 1, "Demo: Ping"),
                                         (2, REQUEST_TIME, "Demo: ping")):
            with self.subTest(channel=channel, timestamp=timestamp, text=text):
                self.assertEqual(evidence.match(channel, timestamp, text).status, "unavailable")

    def test_missing_or_multiple_copies_do_not_invent_metrics_or_a_path(self):
        for copies, status, word in ((0, "unavailable", "unbekannt"), (2, "ambiguous", "mehrdeutig")):
            with self.subTest(copies=copies):
                engine = self.engine()
                for _ in range(copies):
                    engine.observe(receive_frame())
                reply = engine.build(2, REQUEST_TIME, "Demo: Ping", "ping", RESPONSE_TIME)
                self.assert_public_body(reply, "PONG")
                self.assertEqual(reply.evidence_status, status)
                self.assertIn("RX " + word, reply.body)
                for invented in ("🐇", "SNR", "Weg:"):
                    self.assertNotIn(invented, reply.body)

    def test_unknown_and_colliding_prefixes_remain_question_mark_labels(self):
        contacts = {"a1" + "01" * 31: "First", "a1" + "02" * 31: "Other"}
        engine = self.engine(contacts=contacts)
        engine.observe(receive_frame())
        reply = engine.build(2, REQUEST_TIME, "Demo: Ping", "ping", RESPONSE_TIME)
        self.assertIn("Weg: a1?>b2?", reply.body)
        self.assertNotIn("First", reply.body)
        self.assertNotIn("Other", reply.body)

    def test_aliases_do_not_rewrite_original_request_identity(self):
        identities = {report_engine.command_identity(2, REQUEST_TIME, "Demo: " + text)
                      for text in ("ping", "PING", "reping")}
        self.assertEqual(len(identities), 3)
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{64}", identity) for identity in identities))
        with self.assertRaises(ValueError):
            report_engine.command_identity(2, REQUEST_TIME, "Demo: ping\0")

    def test_wrong_reply_family_or_channel_is_rejected_before_packet_preparation(self):
        engine = self.engine()
        engine.observe(receive_frame("Demo: ping test"))
        for channel, command in ((2, "ping"), (3, "test")):
            with self.subTest(channel=channel, command=command):
                with self.assertRaises(ValueError):
                    engine.build(channel, REQUEST_TIME, "Demo: ping test", command, RESPONSE_TIME)
        reply = engine.build(2, REQUEST_TIME, "Demo: ping test", "test", RESPONSE_TIME)
        self.assert_public_body(reply, "TEST")

    def test_utf8_packet_limits_are_fail_closed(self):
        profile = group_sender.FloodProfile(0, None)
        packet = group_sender.group_packet(KEY, "A", "x" * 152, RESPONSE_TIME, profile)
        self.assertLessEqual(len(packet) + 2, 176)
        for alias, body in (("A", "x" * 153), ("🐇" * 8, "ok")):
            with self.subTest(alias=alias, body_bytes=len(body.encode("utf-8"))):
                with self.assertRaises(ValueError):
                    group_sender.group_packet(KEY, alias, body, RESPONSE_TIME, profile)


if __name__ == "__main__":
    unittest.main()
