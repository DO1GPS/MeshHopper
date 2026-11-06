"""Small, synthetic public-core gate; no SDK client, radio, database or socket.

Test dependencies: Python 3.11/3.12, unittest (stdlib), pycryptodome==3.23.0.
The full bot additionally needs meshcore==2.3.14 and its installed dependencies:
bleak, pycayennelpp, pycryptodome, pyserial-asyncio-fast. These tests do not
prove that a real companion/transport, firmware profile or HA install works.

Public source layout, relative to this test's parent directory:
services/bot/{meshcore_room_bot,bot_identity,bot_commands,bot_dialogue,
bot_report,bot_runtime_status,group_sender,local_path_dispatch,path_inference,
reception_evidence,report_engine,report_profile,raw_reply_history}.py
services/bot/{bot_contact_catalog,bot_timing}.py
services/{meshcore_inbox_fetch,meshcore_process_lock,meshcore_command_admission}.py

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
from unittest.mock import patch

ROOT = Path(os.environ.get("MESHCORE_PUBLIC_ROOT", Path(__file__).resolve().parents[1])).resolve()
BOT_SOURCE = ROOT / "services" / "bot"
if not (BOT_SOURCE / "bot_commands.py").is_file():
    raise ImportError("Public core sources missing: run in the export or set MESHCORE_PUBLIC_ROOT")
sys.path.insert(0, str(BOT_SOURCE))

from Crypto.Cipher import AES
import bot_commands
import bot_contact_catalog
import bot_dialogue
import bot_identity
import bot_report
import bot_timing
import group_sender
import reception_evidence
import report_engine

PUBLIC_FILES = (
    "services/bot/meshcore_room_bot.py", "services/bot/bot_identity.py",
    "services/bot/bot_commands.py", "services/bot/bot_dialogue.py",
    "services/bot/bot_report.py", "services/bot/bot_runtime_status.py",
    "services/bot/group_sender.py", "services/bot/reception_evidence.py",
    "services/bot/report_engine.py", "services/bot/report_profile.py",
    "services/bot/raw_reply_history.py", "services/bot/local_path_dispatch.py",
    "services/bot/path_inference.py", "services/meshcore_inbox_fetch.py",
    "services/meshcore_process_lock.py", "services/bot/bot_contact_catalog.py",
    "services/bot/bot_timing.py", "services/meshcore_command_admission.py",
)
KEY = bytes(range(16))
OTHER_KEY = bytes(range(16, 32))
REQUEST_TIME = 1_700_000_000
RESPONSE_TIME = REQUEST_TIME + 1
CONTACTS = {"a1" + "01" * 31: "North", "b2" + "02" * 31: "South"}


def receive_frame(text="Demo: Ping", *, timestamp=REQUEST_TIME,
                  path=(b"\xa1", b"\xb2"), snr_quarters=46, rssi=-100, width=1,
                  key=KEY):
    """Independent version-0 group-text fixture with 1/2/3-byte hops."""
    if width not in (1, 2, 3) or any(len(hop) != width for hop in path):
        raise ValueError("Invalid synthetic path")
    plain = struct.pack("<I", timestamp) + b"\0" + text.encode("utf-8")
    encrypted = AES.new(key, AES.MODE_ECB).encrypt(plain + bytes(-len(plain) % 16))
    mac = hmac.new(key + bytes(16), encrypted, hashlib.sha256).digest()[:2]
    payload = hashlib.sha256(key).digest()[:1] + mac + encrypted
    packet = b"\x15" + bytes([((width - 1) << 6) | len(path)]) + b"".join(path) + payload
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
        self.assertTrue(reply.body.startswith((head if head == "ROOM" else "🏁 " + head) + " @Demo\n"))
        self.assertNotIn("RSSI", reply.body)
        self.assertIsNone(re.search(r"#[0-9a-fA-F]{16}", reply.body))
        self.assertNotIn("\nTX:", reply.body)
        self.assertTrue(reply.body.endswith("\n🏠 nicht gesetzt"))
        self.assertNotIn("Rückweg offen", reply.body)
        self.assertLessEqual(len(reply.body.encode("utf-8")), bot_identity.BOT_BODY_BUDGET)
        self.assertLessEqual(len((reply.sender_alias + ": " + reply.body).encode("utf-8")), 155)
        self.assertLessEqual(len(reply.packet) + 2, 176)
        timestamp, text_type, text = decode_reply(reply.packet)
        self.assertEqual(timestamp, RESPONSE_TIME)
        self.assertEqual(text_type, 0)
        self.assertEqual(text, reply.sender_alias + ": " + reply.body)
        self.assertIsNone(bot_commands.parse_command(text, wire=True),
                          "An actual prepared reply must not trigger another response")

    def test_all_public_source_files_have_only_known_local_or_external_imports(self):
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
        for module in (bot_commands, bot_contact_catalog, bot_identity, bot_report,
                       bot_timing, group_sender, reception_evidence, report_engine):
            with self.subTest(module=module.__name__):
                self.assertEqual(Path(module.__file__).resolve().parent, BOT_SOURCE)

    def test_complete_ascii_commands_produce_one_canonical_family(self):
        cases = {"ping": "ping", "PING": "ping", "reping": "ping",
                 "test": "test", "ReTest": "test", "room": "room",
                 "ROOM": "room", "ping test": "test", "test ping": "test",
                 "reping retest": "test", "ping 123": "ping", "retest 654321": "test",
                 "#ping": "ping", "#reping": "ping", "#test": "test", "#retest": "test",
                 "#room": "room", "#ping test": "test", "#test ping 12": "test",
                 "Danke": "thanks", "thanks": "thanks", "danke 73": "thanks",
                 "@MeshHopper danke": "thanks", "@MeshHopper thanks 73": "thanks",
                 "pfad": "path", "#PFAD": "path", "path": "path", "weg": "path",
                 "way": "path", "route": "path", "hilfe": "help", "help": "help", "dir": "help",
                 "#hilfe": "help", "#help": "help", "#dir": "help"}
        for text, command in cases.items():
            with self.subTest(text=text):
                self.assertEqual(bot_commands.parse_command(text), command)
                self.assertEqual(bot_commands.parse_command("Demo: " + text, wire=True), command)

    def test_sentence_unicode_lookalike_and_embedded_control_do_not_trigger(self):
        for text in ("please ping me", "ping ping", "room test", "ping 1234567",
                     "PİNG", "ＰＩＮＧ", "ping\n test", "pi\0ng", "Demo: ping",
                     "##ping", "# ping", "ping #test", "Ping von 55566", "ping he",
                     "danke dafür", "thanks 123", "#danke", None, 1):
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
                self.assertEqual(reply.body.splitlines(), [(head if head == "ROOM" else "🏁 " + head) + " @Demo",
                                                          "📡 2 🐇 | SNR +11.5 dB",
                                                          "📩 Nort → Sout", "🏠 nicht gesetzt"])
                self.assertEqual(observed.copies[0].rssi_dbm, -100)
                self.assertEqual(reply.request_identity, report_engine.command_identity(2, REQUEST_TIME, text))

    def test_zero_hops_snr_and_rssi_are_real_values_not_missing(self):
        engine = self.engine()
        observed = engine.observe(receive_frame(path=(), snr_quarters=0, rssi=0))
        reply = engine.build(2, REQUEST_TIME, "Demo: Ping", "ping", RESPONSE_TIME)
        self.assert_public_body(reply, "PONG")
        self.assertIn("📡 0 🐇 | SNR +0 dB\n📩 direkt", reply.body)
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

    def test_missing_copy_does_not_invent_metrics_or_a_path(self):
        reply = self.engine().build(2, REQUEST_TIME, "Demo: Ping", "ping", RESPONSE_TIME)
        self.assert_public_body(reply, "PONG")
        self.assertEqual(reply.evidence_status, "unavailable")
        self.assertEqual(reply.body.splitlines(), ["🏁 PONG @Demo", "📡 unbekannt",
                                                  "📩 nicht erfasst", "🏠 nicht gesetzt"])
        self.assertNotIn("🐇", reply.body)
        self.assertNotIn("SNR", reply.body)

    def test_multiple_exact_copies_report_the_first_whole_copy_without_crossmixing(self):
        engine = self.engine()
        first = engine.observe(receive_frame(path=(b"\xa1", b"\xb2"), snr_quarters=46, rssi=-100))
        engine.observe(receive_frame(path=(b"\xb2",), snr_quarters=-20, rssi=-120))
        before = dict(engine._pending)
        with patch.object(report_engine, "response_body", wraps=bot_report.response_body) as formatter:
            reply = engine.build(2, REQUEST_TIME, "Demo: Ping", "ping", RESPONSE_TIME)
        matched = formatter.call_args.args[1]
        self.assertEqual((matched.status, matched.reason), ("ambiguous", "multiple_rx_copies"))
        self.assertEqual(len(matched.copies), 2)
        self.assertEqual(matched.copies[0], first.copies[0])
        self.assert_public_body(reply, "PONG")
        self.assertEqual(reply.evidence_status, "ambiguous")
        self.assertEqual(reply.body.splitlines(), ["🏁 PONG @Demo",
                                                  "📡 2 🐇 | SNR +11.5 dB",
                                                  "📩 Nort → Sout", "🏠 nicht gesetzt"])
        self.assertNotIn("📡 1 🐇", reply.body)
        self.assertNotIn("SNR -5 dB", reply.body)
        # Formatting does not erase either complete input or claim a unique route.
        self.assertEqual(engine._pending, before)

    def test_unknown_and_colliding_prefixes_remain_short_hashes_without_invented_names(self):
        contacts = {"a1" + "01" * 31: "First", "a1" + "02" * 31: "Other"}
        engine = self.engine(contacts=contacts)
        engine.observe(receive_frame())
        reply = engine.build(2, REQUEST_TIME, "Demo: Ping", "ping", RESPONSE_TIME)
        self.assertIn("📩 A1 → B2", reply.body)
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

    def test_thanks_packet_has_the_exact_reply_and_does_not_trigger_another_reply(self):
        for request in ("Danke", "thanks", "danke 73", "@MeshHopper thanks 73"):
            with self.subTest(request=request):
                engine = self.engine()
                text = "Demo: " + request
                engine.observe(receive_frame(text))
                reply = engine.build(2, REQUEST_TIME, text, "thanks", RESPONSE_TIME)
                self.assertIn(reply.body, bot_dialogue.COURTESY_REPLIES)
                self.assertEqual(reply.sender_alias, "🐇 MeshHopper")
                self.assertLessEqual(len((reply.sender_alias + ": " + reply.body).encode("utf-8")), 155)
                timestamp, kind, outgoing = decode_reply(reply.packet)
                self.assertEqual((timestamp, kind), (RESPONSE_TIME, 0))
                self.assertEqual(outgoing, reply.sender_alias + ": " + reply.body)
                self.assertIsNone(bot_commands.parse_command(outgoing, wire=True))

    def test_known_bot_thanks_and_other_reply_bodies_do_not_start_a_loop(self):
        for alias in bot_identity.KNOWN_BOT_ALIASES:
            for body in ("danke", "thanks 73", *bot_dialogue.COURTESY_REPLIES, "PONG @Demo"):
                with self.subTest(alias=alias, body=body):
                    self.assertIsNone(bot_commands.parse_command(alias + ": " + body, wire=True))
        for body in ("PONG @Demo", "TEST @Demo", "ROOM @Demo", *bot_dialogue.COURTESY_REPLIES):
            self.assertIsNone(bot_commands.parse_command(body))

    def test_addressed_pong_from_is_bounded_and_terminal(self):
        text = "@MeshHopper pong from Demo Station"
        self.assertEqual(bot_commands.parse_command(text), "path_context")
        self.assertEqual(bot_report.response_body(
            "path_context", reception_evidence.EvidenceResult("unavailable", "synthetic"), {}, None),
            bot_dialogue.PATH_CONTEXT_REPLY)
        self.assertIsNone(bot_commands.parse_command("@MeshHopper " + bot_dialogue.PATH_CONTEXT_REPLY))
        self.assertLessEqual(len(bot_dialogue.PATH_CONTEXT_REPLY.encode("utf-8")),
                             bot_identity.BOT_BODY_BUDGET)
        for invalid in ("pong from Demo Station", "@MeshHopper pong from -",
                        "@MeshHopper pong from [Demo]", "@Other pong from Demo"):
            with self.subTest(invalid=invalid):
                self.assertNotEqual(bot_commands.parse_command(invalid), "path_context")

    def test_public_qth_is_local_and_display_controls_cannot_create_extra_lines(self):
        self.assertEqual(bot_report.MONITOR_QTH, "nicht gesetzt")
        source = (BOT_SOURCE / "bot_report.py").read_text(encoding="utf-8")
        self.assertIn('os.environ.get("MESHCORE_MONITOR_QTH", "nicht gesetzt")', source)
        engine = self.engine()
        engine.observe(receive_frame())
        with patch.object(bot_report, "MONITOR_QTH", "Demo\nLoc\u200b | <>"):
            reply = engine.build(2, REQUEST_TIME, "Demo: Ping", "ping", RESPONSE_TIME)
        self.assertEqual(len(reply.body.splitlines()), 4)
        self.assertEqual(reply.body.splitlines()[-1], "🏠 DemoLoc")
        self.assertNotIn("\u200b", reply.body)

    def test_utf8_packet_limits_are_fail_closed(self):
        profile = group_sender.FloodProfile(0, None)
        packet = group_sender.group_packet(KEY, "A", "x" * 152, RESPONSE_TIME, profile)
        self.assertLessEqual(len(packet) + 2, 176)
        for alias, body in (("A", "x" * 153), ("🐇" * 8, "ok")):
            with self.subTest(alias=alias, body_bytes=len(body.encode("utf-8"))):
                with self.assertRaises(ValueError):
                    group_sender.group_packet(KEY, alias, body, RESPONSE_TIME, profile)

    def test_normal_report_keeps_four_edges_and_explicit_middle_omission(self):
        path = tuple(bytes([value]) for value in (0xBF, 0x84, 0x99, 0x38, 0x6C, 0xAA, 0x44, 0x3C))
        engine = self.engine(contacts={})
        observed = engine.observe(receive_frame(path=path))
        reply = engine.build(2, REQUEST_TIME, "Demo: Ping", "ping", RESPONSE_TIME)
        self.assert_public_body(reply, "PONG")
        self.assertEqual(reply.body.splitlines()[2], "📩 BF → 84 → … → 44 → 3C")
        self.assertLessEqual(len(reply.body.splitlines()[2][2:]), 22)
        self.assertEqual(observed.copies[0].path_hashes, tuple(hop.hex() for hop in path))

    def test_long_named_summary_keeps_whole_callsigns_at_both_ends(self):
        path = tuple(bytes([i]) for i in range(1, 7))
        contacts = {hop.hex() + "00" * 31: name for hop, name in zip(path,
                    ("DB0KT", "Example-North", "Middle", "Other", "Example-South", "DO1GPS"))}
        engine = self.engine(contacts=contacts)
        engine.observe(receive_frame(path=path))
        reply = engine.build(2, REQUEST_TIME, "Demo: Ping", "ping", RESPONSE_TIME)
        self.assertEqual(reply.body.splitlines()[2], "📩 DB0KT → … → DO1GPS")
        self.assert_public_body(reply, "PONG")

    def test_pfad_keeps_every_position_full_prefix_and_numbered_packets(self):
        for width, count in ((1, 63), (2, 32), (3, 20)):
            path = tuple(bytes([i]) + bytes(range(1, width)) for i in range(1, count + 1))
            engine = self.engine(contacts={})
            engine.observe(receive_frame("Demo: Ping", path=path, width=width))
            engine.remember_probe(2, REQUEST_TIME, "Demo: Ping")
            engine.complete(2, REQUEST_TIME, "Demo: Ping")
            text = "Other: #PFAD"
            replies = engine.build_path(2, REQUEST_TIME + 1, text, RESPONSE_TIME)
            self.assertGreater(len(replies), 1)
            lines = []
            for index, reply in enumerate(replies, 1):
                self.assertEqual(reply.body.splitlines()[0], f"📩 RX-Weg @Demo · {index}/{len(replies)}")
                self.assertEqual((reply.part_index, reply.part_total), (index, len(replies)))
                self.assertLessEqual(len(reply.body.encode()), bot_identity.BOT_BODY_BUDGET)
                self.assertLessEqual(len(reply.packet) + 2, 176)
                self.assertEqual(decode_reply(reply.packet), (RESPONSE_TIME, 0, reply.sender_alias + ": " + reply.body))
                self.assertIsNone(bot_commands.parse_command(reply.body))
                self.assertEqual(reply.request_identity,
                                 report_engine.command_identity(2, REQUEST_TIME + 1, text))
                lines.extend(reply.body.splitlines()[1:])
            self.assertEqual(lines, [f"{index:02d} → [{hop.hex().upper()}]" for index, hop in enumerate(path, 1)]
                             + ["🏠 Ziel → nicht gesetzt"])
            self.assertEqual(len({reply.packet_identity for reply in replies}), len(replies))

    def test_pfad_uses_last_admitted_ping_not_the_different_requesters_own_path(self):
        engine = self.engine(contacts={})
        engine.observe(receive_frame(path=(b"\xa1", b"\xb2")))
        engine.remember_probe(2, REQUEST_TIME, "Demo: Ping")
        engine.complete(2, REQUEST_TIME, "Demo: Ping")
        engine.observe(receive_frame("Other: pfad", timestamp=REQUEST_TIME + 1,
                                     path=(b"\xcc",)))
        replies = engine.build_path(2, REQUEST_TIME + 1, "Other: pfad", RESPONSE_TIME)
        self.assertEqual(replies[0].body,
                         "📩 RX-Weg @Demo\n01 → [A1]\n02 → [B2]\n🏠 Ziel → nicht gesetzt")
        self.assertNotIn("1/1", replies[0].body)
        self.assertEqual(replies[0].evidence_status, "available")
        self.assertEqual(replies[0].request_identity,
                         report_engine.command_identity(2, REQUEST_TIME + 1, "Other: pfad"))
        self.assertEqual(decode_reply(replies[0].packet),
                         (RESPONSE_TIME, 0, replies[0].sender_alias + ": " + replies[0].body))

    def test_pfad_targets_are_channel_local_and_not_carried_to_a_new_session(self):
        engine = report_engine.BotReportEngine(
            {2: KEY, 5: OTHER_KEY}, group_sender.FloodProfile(0, None), None, {},
        )
        for channel, key, text, path in ((2, KEY, "Demo: Ping", b"\xa1"),
                                         (5, OTHER_KEY, "Remote: test", b"\xb2")):
            engine.observe(receive_frame(text, key=key, path=(path,)))
            engine.remember_probe(channel, REQUEST_TIME, text)
            engine.complete(channel, REQUEST_TIME, text)
        self.assertEqual(engine.build_path(2, REQUEST_TIME + 1, "Other: pfad", RESPONSE_TIME)[0].body,
                         "📩 RX-Weg @Demo\n01 → [A1]\n🏠 Ziel → nicht gesetzt")
        self.assertEqual(engine.build_path(5, REQUEST_TIME + 1, "Other: pfad", RESPONSE_TIME)[0].body,
                         "📩 RX-Weg @Remote\n01 → [B2]\n🏠 Ziel → nicht gesetzt")
        fresh = self.engine(contacts={})
        self.assertEqual(fresh.build_path(2, REQUEST_TIME + 1, "Other: pfad", RESPONSE_TIME)[0].body,
                         "📩 Noch kein Ping/Test in diesem Kanal")

    def test_pfad_without_admitted_ping_does_not_select_raw_or_requester(self):
        engine = self.engine(contacts={})
        engine.observe(receive_frame("Unadmitted: Ping"))
        engine.observe(receive_frame("Other: pfad", path=()))
        replies = engine.build_path(2, REQUEST_TIME, "Other: pfad", RESPONSE_TIME)
        self.assertEqual(replies[0].body, "📩 Noch kein Ping/Test in diesem Kanal")
        self.assertEqual(replies[0].evidence_status, "unavailable")

    def test_pfad_new_probe_missing_raw_never_borrows_the_previous_path(self):
        engine = self.engine(contacts={})
        engine.observe(receive_frame())
        engine.remember_probe(2, REQUEST_TIME, "Demo: Ping")
        engine.complete(2, REQUEST_TIME, "Demo: Ping")
        engine.remember_probe(2, REQUEST_TIME + 1, "New: test")
        engine.complete(2, REQUEST_TIME + 1, "New: test")
        engine.observe(receive_frame("Other: pfad", path=(b"\xcc",)))
        replies = engine.build_path(2, REQUEST_TIME + 2, "Other: pfad", RESPONSE_TIME)
        self.assertEqual(replies[0].body, "📩 RX-Weg @New\nEmpfangspfad nicht erfasst")
        self.assertEqual(replies[0].evidence_status, "unavailable")

    def test_pfad_late_exact_raw_updates_completed_probe_but_not_neighbor_events(self):
        engine = self.engine(contacts={})
        engine.remember_probe(2, REQUEST_TIME, "Demo: Ping")
        engine.complete(2, REQUEST_TIME, "Demo: Ping")
        engine.observe(receive_frame("Demo: Ping", timestamp=REQUEST_TIME + 1,
                                     path=(b"\xcc",)))
        engine.observe(receive_frame("Other: Ping", path=(b"\xdd",)))
        missing = engine.build_path(2, REQUEST_TIME + 2, "Reader: pfad", RESPONSE_TIME)
        self.assertIn("nicht erfasst", missing[0].body)
        engine.observe(receive_frame("Demo: Ping", path=(b"\xa1",)))
        replies = engine.build_path(2, REQUEST_TIME + 2, "Reader: pfad", RESPONSE_TIME)
        self.assertEqual(replies[0].body,
                         "📩 RX-Weg @Demo\n01 → [A1]\n🏠 Ziel → nicht gesetzt")

    def test_pfad_first_whole_copy_and_frozen_retime_do_not_mix_later_target(self):
        engine = self.engine(contacts={})
        engine.remember_probe(2, REQUEST_TIME, "Demo: Ping")
        engine.complete(2, REQUEST_TIME, "Demo: Ping")
        path = (b"\xaa\xbb", b"\xcc\xdd", b"\xaa\xbb")
        engine.observe(receive_frame("Demo: Ping", path=path, width=2))
        engine.observe(receive_frame("Demo: Ping", path=(b"\xee\xff",), width=2))
        replies = engine.build_path(2, REQUEST_TIME + 2, "Reader: pfad", RESPONSE_TIME)
        self.assertEqual(replies[0].evidence_status, "ambiguous")
        self.assertEqual(replies[0].body.splitlines(), ["📩 RX-Weg @Demo", "01 → [AABB]",
                                                       "02 → [CCDD]", "03 → [AABB]",
                                                       "🏠 Ziel → nicht gesetzt"])
        engine.remember_probe(2, REQUEST_TIME - 10, "Later: test")
        newer = engine.build_path(2, REQUEST_TIME + 3, "Reader: #pfad", RESPONSE_TIME)
        self.assertIn("@Later", newer[0].body, "Inbox order, not sender clock, selects last")
        retimed = engine.retime_path(replies, RESPONSE_TIME + 5)
        for original, final in zip(replies, retimed):
            self.assertEqual((original.body, original.evidence_status, original.request_identity,
                              original.part_index, original.part_total),
                             (final.body, final.evidence_status, final.request_identity,
                              final.part_index, final.part_total))
            self.assertEqual(decode_reply(final.packet),
                             (RESPONSE_TIME + 5, 0, final.sender_alias + ": " + original.body))
            self.assertNotEqual(original.packet_identity, final.packet_identity)

    def test_pfad_state_is_bounded_per_configured_channel_and_two_whole_copies(self):
        engine = self.engine(contacts={})
        for index in range(150):
            text = f"Demo{index}: Ping"
            engine.observe(receive_frame(text, timestamp=REQUEST_TIME + index, path=()))
            engine.remember_probe(2, REQUEST_TIME + index, text)
            engine.complete(2, REQUEST_TIME + index, text)
        for value in range(10):
            engine.observe(receive_frame("Demo149: Ping", timestamp=REQUEST_TIME + 149,
                                         path=(bytes([value]),)))
        self.assertEqual(len(engine._last_probes), 1)
        self.assertLessEqual(len(engine._last_probes[2][2].copies), 2)
        self.assertEqual(engine.pending_count, 0)
        self.assertIn("@Demo149", engine.build_path(2, REQUEST_TIME + 151,
                                                 "Reader: pfad", RESPONSE_TIME)[0].body)

    def test_pfad_full_labels_are_not_the_compact_ping_labels(self):
        contacts = {"aabb" + "01" * 30: "DE-HE-Example-Hill-North"}
        engine = self.engine(contacts=contacts)
        engine.observe(receive_frame(path=(b"\xaa\xbb",), width=2))
        engine.remember_probe(2, REQUEST_TIME, "Demo: Ping")
        replies = engine.build_path(2, REQUEST_TIME + 1, "Other: pfad", RESPONSE_TIME)
        self.assertEqual(replies[0].body,
                         "📩 RX-Weg @Demo\n01 → DE-HE-Example-Hill-North [AABB]\n"
                         "🏠 Ziel → nicht gesetzt")

    def test_passive_catalog_session_revision_and_capacity_preserve_ambiguity(self):
        session = object()
        catalog = bot_contact_catalog.BotContactCatalog(session, capacity=2)
        first, second = "a1" + "01" * 31, "a1" + "02" * 31
        self.assertTrue(catalog.merge_records({first: {"adv_name": "Example-North"}},
                        session_token=session, revision=1))
        snapshot = catalog.snapshot()
        self.assertFalse(catalog.merge_records({first: {"adv_name": "Stale"}},
                         session_token=session, revision=1))
        self.assertFalse(catalog.observe_key(second, session_token=object(), revision=2))
        self.assertTrue(catalog.observe_key(second, session_token=session, revision=2))
        self.assertEqual(snapshot, {first: "Example-North"}, "Old snapshots must stay immutable")
        engine = report_engine.BotReportEngine({2: KEY}, group_sender.FloodProfile(0, None),
                                               None, {}, contact_catalog=catalog)
        engine.observe(receive_frame(path=(b"\xa1",)))
        reply = engine.build(2, REQUEST_TIME, "Demo: Ping", "ping", RESPONSE_TIME)
        self.assertIn("📩 A1", reply.body, "An unnamed second candidate prevents a false unique name")
        self.assertFalse(catalog.observe_key("b2" + "03" * 31, session_token=session, revision=3))
        self.assertTrue(catalog.coverage_lost)
        self.assertEqual(dict(catalog.snapshot()), {})

    def test_timing_is_bounded_noninvasive_and_does_not_claim_rf_delivery(self):
        events = []
        samples = iter((100, 1000))
        trace = bot_timing.RequestTiming("01" * 32, 2, "02" * 16,
                     lambda kind, **payload: events.append((kind, payload)), clock=lambda: next(samples))
        for _ in range(bot_timing.MAX_SPAN_COUNT + 2):
            trace.record("sdk_send_raw_packet", 1)
        trace.finish()
        trace.finish()
        self.assertEqual(len(events), 1)
        kind, payload = events[0]
        self.assertEqual(kind, "bot_timing")
        self.assertEqual(payload["spans"]["sdk_send_raw_packet"]["count"], bot_timing.MAX_SPAN_COUNT)
        self.assertFalse(payload["measurements_complete"])
        self.assertFalse(payload["rf_delivery_proven"])
        self.assertEqual(payload["sdk_span_scope"], "admission_relay_transport_device_response")
        trace = bot_timing.RequestTiming("01" * 32, 2, "02" * 16,
                     lambda *args, **kwargs: (_ for _ in ()).throw(OSError("fixture")), clock=lambda: 1)
        trace.finish()  # A diagnostic output failure must not reach the caller.

    def test_help_aliases_have_one_short_packet_without_reception_claims(self):
        for command in ("hilfe", "help", "dir", "#hilfe", "#help", "#dir"):
            reply = self.engine().build(2, REQUEST_TIME, "Demo: " + command, "help", RESPONSE_TIME)
            self.assertEqual(reply.body, bot_report.HELP_REPLY)
            self.assertEqual(reply.evidence_status, "unavailable")
            self.assertLessEqual(len(reply.body.encode()), bot_identity.BOT_BODY_BUDGET)
            self.assertLessEqual(len(reply.packet) + 2, 176)
            self.assertEqual(decode_reply(reply.packet), (RESPONSE_TIME, 0, reply.sender_alias + ": " + reply.body))
            self.assertIsNone(bot_commands.parse_command(reply.sender_alias + ": " + reply.body, wire=True))
        for text in ("help me", "hilfe ping", "# dir", "dir 1", "##help", "directory"):
            self.assertIsNone(bot_commands.parse_command(text))


if __name__ == "__main__":
    unittest.main()
