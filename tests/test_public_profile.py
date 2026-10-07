"""Synthetic public device-profile gate; no installed SDK, socket or radio.

The workspace tests the staged public source; an export tests its own source.
Names and key bytes below are invented fixtures, never operator configuration.
"""
from __future__ import annotations

import importlib.util
from enum import Enum, auto
import os
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
STAGED_PROFILE = ROOT / "docs" / "public" / "release_staging" / "report_profile.py"
PROFILE_SOURCE = (STAGED_PROFILE if STAGED_PROFILE.is_file() else
                  ROOT / "services" / "bot" / "report_profile.py")
sys.path.insert(0, str(ROOT / "services" / "bot"))


class EventType(Enum):
    SELF_INFO = auto()
    DEVICE_INFO = auto()
    DEFAULT_FLOOD_SCOPE = auto()
    CHANNEL_INFO = auto()
    CONTACTS = auto()
    ERROR = auto()


sdk_fixture = ModuleType("meshcore")
sdk_fixture.EventType = EventType
profile_spec = importlib.util.spec_from_file_location("public_report_profile_under_test", PROFILE_SOURCE)
if profile_spec is None or profile_spec.loader is None:
    raise ImportError("Public device-profile source unavailable")
profile = importlib.util.module_from_spec(profile_spec)
with patch.dict(sys.modules, {"meshcore": sdk_fixture}):
    profile_spec.loader.exec_module(profile)


KEY = bytes(range(16))
SCOPE_KEY = bytes(range(16, 32))


def event(kind, payload):
    return SimpleNamespace(type=kind, payload=payload)


def self_info(name="Demo Alpha"):
    return event(EventType.SELF_INFO, {"name": name})


class QueryFixture:
    def __init__(self):
        self.calls = []
        self.device = event(EventType.DEVICE_INFO, {
            "ver": "v1.17.1-d929643", "model": "Seeed Wio Tracker L1", "path_hash_mode": 0,
        })
        self.scope = event(EventType.DEFAULT_FLOOD_SCOPE, {})
        self.channel = event(EventType.CHANNEL_INFO, {
            "channel_idx": 2, "channel_name": "Demo channel", "channel_secret": KEY.hex(),
        })
        self.contacts = event(EventType.CONTACTS, {})

    async def send_device_query(self):
        self.calls.append("device")
        return self.device

    async def get_default_flood_scope(self):
        self.calls.append("scope")
        return self.scope

    async def get_channel(self, index):
        self.calls.append(("channel", index))
        return self.channel

    async def get_contacts(self):
        self.calls.append("contacts")
        return self.contacts


class PublicProfileTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        local_name = patch.dict(os.environ, {"MESHCORE_COMPANION_NAME": "Demo Alpha"})
        local_name.start()
        self.addCleanup(local_name.stop)
        self.queries = QueryFixture()
        self.client = SimpleNamespace(commands=self.queries)

    async def read(self, identity=None):
        return await profile.read_report_engine(
            self.client, {2}, self_info() if identity is None else identity,
        )

    async def assert_identity_rejected(self, identity):
        with self.assertRaisesRegex(ValueError, "Unexpected device identity"):
            await profile.read_report_engine(self.client, {2}, identity)
        self.assertEqual(self.queries.calls, [])

    async def test_missing_local_name_rejects_before_queries(self):
        os.environ.pop("MESHCORE_COMPANION_NAME", None)
        with self.assertRaisesRegex(ValueError, "MESHCORE_COMPANION_NAME"):
            await self.read()
        self.assertEqual(self.queries.calls, [])

    async def test_empty_local_name_rejects_before_queries(self):
        for empty in ("", " ", "\t\n"):
            with self.subTest(empty=repr(empty)):
                os.environ["MESHCORE_COMPANION_NAME"] = empty
                with self.assertRaisesRegex(ValueError, "MESHCORE_COMPANION_NAME"):
                    await self.read()
                self.assertEqual(self.queries.calls, [])

    async def test_wrong_name_rejects_before_queries(self):
        await self.assert_identity_rejected(self_info("Demo Beta"))

    async def test_name_match_is_exact(self):
        for different in ("demo alpha", " Demo Alpha", "Demo Alpha "):
            with self.subTest(identity=different):
                await self.assert_identity_rejected(self_info(different))

    async def test_wrong_self_info_event_rejects_before_queries(self):
        await self.assert_identity_rejected(event(EventType.DEVICE_INFO, {"name": "Demo Alpha"}))

    async def test_missing_self_info_rejects_before_queries(self):
        await self.assert_identity_rejected(None)

    async def test_malformed_self_info_rejects_before_queries(self):
        for identity in (object(), event(EventType.SELF_INFO, None),
                         event(EventType.SELF_INFO, {})):
            with self.subTest(identity=type(identity).__name__):
                await self.assert_identity_rejected(identity)

    async def test_first_configured_name_accepts_complete_profile(self):
        engine = await self.read()
        self.assertIsInstance(engine, profile.BotReportEngine)
        self.assertEqual(engine._channels, {2: KEY})
        self.assertIsNone(engine._scope_name)
        self.assertEqual(self.queries.calls, ["device", "scope", ("channel", 2), "contacts"])

    async def test_second_configured_name_accepts_complete_profile(self):
        os.environ["MESHCORE_COMPANION_NAME"] = "Demo Beta"
        engine = await self.read(self_info("Demo Beta"))
        self.assertIsInstance(engine, profile.BotReportEngine)
        self.assertEqual(self.queries.calls, ["device", "scope", ("channel", 2), "contacts"])

    async def test_missing_or_wrong_device_event_rejects(self):
        for wrong in (None, event(EventType.ERROR, {})):
            with self.subTest(event=wrong is None):
                self.queries.device = wrong
                with self.assertRaisesRegex(ValueError, "Unsupported raw sender device profile"):
                    await self.read()
                self.assertNotIn("scope", self.queries.calls)

    async def test_unsupported_model_rejects(self):
        self.queries.device.payload["model"] = "Demo unsupported model"
        with self.assertRaisesRegex(ValueError, "Unsupported raw sender device profile"):
            await self.read()
        self.assertEqual(self.queries.calls, ["device"])

    async def test_unsupported_firmware_rejects(self):
        self.queries.device.payload["ver"] = "v0.0.0-demo"
        with self.assertRaisesRegex(ValueError, "Unsupported raw sender device profile"):
            await self.read()
        self.assertEqual(self.queries.calls, ["device"])

    async def test_unsupported_path_mode_rejects(self):
        for mode in (None, True, 3):
            with self.subTest(mode=mode):
                self.queries.device.payload["path_hash_mode"] = mode
                with self.assertRaises(ValueError):
                    await self.read()
                self.assertNotIn(("channel", 2), self.queries.calls)

    async def test_missing_or_wrong_scope_event_rejects(self):
        for wrong in (None, event(EventType.ERROR, {})):
            with self.subTest(event=wrong is None):
                self.queries.scope = wrong
                with self.assertRaisesRegex(ValueError, "Scope profile unavailable"):
                    await self.read()
                self.assertNotIn(("channel", 2), self.queries.calls)

    async def test_invalid_scope_name_rejects(self):
        for name in (None, "", " "):
            with self.subTest(name=name):
                self.queries.scope.payload = {"scope_name": name, "scope_key": SCOPE_KEY.hex()}
                with self.assertRaisesRegex(ValueError, "Invalid scope name"):
                    await self.read()
                self.assertNotIn(("channel", 2), self.queries.calls)

    async def test_invalid_scope_secret_rejects(self):
        for secret in (None, "", "not hex", "00" * 16, "01" * 15):
            with self.subTest(secret_type=type(secret).__name__):
                self.queries.scope.payload = {"scope_name": "Demo scope", "scope_key": secret}
                with self.assertRaises(ValueError):
                    await self.read()
                self.assertNotIn(("channel", 2), self.queries.calls)

    async def test_valid_scope_retains_configured_profile(self):
        self.queries.scope.payload = {"scope_name": "Demo scope", "scope_key": SCOPE_KEY.hex()}
        engine = await self.read()
        self.assertEqual(engine._scope_name, "Demo scope")
        self.assertEqual(engine._profile.scope_key, SCOPE_KEY)

    async def test_missing_or_wrong_channel_event_rejects(self):
        for wrong in (None, event(EventType.ERROR, {})):
            with self.subTest(event=wrong is None):
                self.queries.channel = wrong
                with self.assertRaisesRegex(ValueError, "Channel profile unavailable"):
                    await self.read()
                self.assertNotIn("contacts", self.queries.calls)

    async def test_wrong_channel_index_rejects(self):
        for index in (None, True, 3):
            with self.subTest(index=index):
                self.queries.channel.payload["channel_idx"] = index
                with self.assertRaisesRegex(ValueError, "Channel profile unavailable"):
                    await self.read()
                self.assertNotIn("contacts", self.queries.calls)

    async def test_missing_channel_name_rejects(self):
        self.queries.channel.payload["channel_name"] = ""
        with self.assertRaisesRegex(ValueError, "Channel profile unavailable"):
            await self.read()
        self.assertNotIn("contacts", self.queries.calls)

    async def test_invalid_channel_secret_rejects(self):
        for secret in (None, "", "not hex", "01" * 15):
            with self.subTest(secret_type=type(secret).__name__):
                self.queries.channel.payload["channel_secret"] = secret
                with self.assertRaises(ValueError):
                    await self.read()

    async def test_missing_or_wrong_contacts_event_rejects(self):
        for wrong in (None, event(EventType.ERROR, {})):
            with self.subTest(event=wrong is None):
                self.queries.contacts = wrong
                with self.assertRaisesRegex(ValueError, "Contact snapshot unavailable"):
                    await self.read()


if __name__ == "__main__":
    unittest.main()
