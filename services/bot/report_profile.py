"""Read-only raw-QSL prerequisite queries with a locally configured device name.

The public draft requires MESHCORE_COMPANION_NAME. No operator identity is
embedded and the configured display name must match exactly before queries.
"""
import os

from meshcore import EventType
from group_sender import FloodProfile
from report_engine import BotReportEngine


async def read_report_engine(client, channels, self_info):
    expected_name = os.environ.get("MESHCORE_COMPANION_NAME")
    if not expected_name or not expected_name.strip():
        raise ValueError("Set MESHCORE_COMPANION_NAME locally before using raw-QSL")
    if (self_info is None or getattr(self_info, "type", None) != EventType.SELF_INFO or
            not isinstance(getattr(self_info, "payload", None), dict) or
            self_info.payload.get("name") != expected_name):
        raise ValueError("Unexpected device identity")
    device = await client.commands.send_device_query()
    if (device is None or device.type != EventType.DEVICE_INFO or
            device.payload.get("ver", "").lstrip("v") != "1.17.1-d929643" or
            device.payload.get("model") != "Seeed Wio Tracker L1"):
        raise ValueError("Unsupported raw sender device profile")
    mode = device.payload.get("path_hash_mode")
    scope = await client.commands.get_default_flood_scope()
    if scope is None or scope.type != EventType.DEFAULT_FLOOD_SCOPE:
        raise ValueError("Scope profile unavailable")
    scope_name = scope_key = None
    if scope.payload:
        scope_name = scope.payload.get("scope_name")
        secret = scope.payload.get("scope_key")
        scope_key = bytes.fromhex(secret) if isinstance(secret, str) else b""
        if not isinstance(scope_name, str) or not scope_name.strip():
            raise ValueError("Invalid scope name")
    profile = FloodProfile(mode, scope_key)
    keys = {}
    for index in sorted(channels):
        event = await client.commands.get_channel(index)
        if (event is None or event.type != EventType.CHANNEL_INFO or
                type(event.payload.get("channel_idx")) is not int or event.payload["channel_idx"] != index or
                not event.payload.get("channel_name")):
            raise ValueError("Channel profile unavailable")
        secret = event.payload.get("channel_secret")
        keys[index] = bytes.fromhex(secret) if isinstance(secret, str) else secret
    contacts_event = await client.commands.get_contacts()
    if contacts_event is None or contacts_event.type != EventType.CONTACTS:
        raise ValueError("Contact snapshot unavailable")
    contacts = {key: data.get("adv_name", "") for key, data in contacts_event.payload.items()
                if isinstance(data, dict)}
    # Explicit policy: the bot uses the stored default scope in each raw
    # packet, NOT the unqueryable temporary override and never changes either.
    return BotReportEngine(keys, profile, scope_name, contacts)
