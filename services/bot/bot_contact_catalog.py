"""Bounded passive name candidates; no SDK calls, timers or identity guesses.

CONTACTS is an end-of-stream batch, not necessarily a full inventory: the
shared transport can carry lastmod/delta requests. Merge only at that event,
never NEXT_CONTACT. Key-only adverts add candidates without clearing names.
The owning SDK session supplies ordered revisions and an opaque session token.
"""
from types import MappingProxyType


def _key(value):
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _entry(key, item):
    if (not _key(key) or not isinstance(item, dict)
            or item.get("public_key", key) != key
            or not isinstance(item.get("adv_name"), str)):
        return None
    try:
        if len(item["adv_name"].encode("utf-8", "strict")) > 128:
            return None
    except UnicodeError:
        return None
    stamp = item.get("lastmod")
    if stamp is not None and (type(stamp) is not int or not 0 <= stamp <= 0xffffffff):
        return None
    # lastmod belongs to the device RTC, NOT a monotone receive version.
    return item["adv_name"], stamp


class BotContactCatalog:
    def __init__(self, session_token, *, capacity=4096):
        if session_token is None or type(capacity) is not int or not 1 <= capacity <= 65536:
            raise ValueError("Invalid contact catalog context")
        self._session_token = session_token
        self._capacity = capacity
        self._records = {}
        self._staged = {}
        self._snapshot = MappingProxyType({})
        self.revision = 0
        self.coverage_lost = False

    def _current(self, session_token, revision):
        return (session_token is self._session_token and type(revision) is int
                and revision > self.revision)

    def merge_records(self, payload, *, session_token, revision,
                      only_missing=False, staged=False):
        if not self._current(session_token, revision) or not isinstance(payload, dict):
            return False
        if len(payload) > self._capacity:
            self.coverage_lost = True
            self._snapshot = MappingProxyType({})
            self.revision = revision
            return False
        # Validate the entire batch before committing any entry. A malformed
        # partial batch cannot silently replace or partially mutate the catalog.
        entries = {}
        for key, item in payload.items():
            entry = _entry(key, item)
            if entry is None:
                return False
            staged_entry = self._staged.get(key)
            source_revision = (staged_entry[2] if staged_entry is not None
                and staged_entry[:2] == entry else 0) if staged else revision
            entries[key] = (*entry, source_revision)
        if len(self._records.keys() | entries.keys()) > self._capacity:
            # No eviction that could turn an ambiguous prefix into a unique
            # candidate. Once coverage is lost, names stay unavailable this session.
            self.coverage_lost = True
            self._snapshot = MappingProxyType({})
            self.revision = revision
            return False
        updated = dict(self._records)
        for key, entry in entries.items():
            previous = updated.get(key)
            if previous is not None and (only_missing or entry[2] <= previous[2]):
                continue
            updated[key] = entry
        self._records = updated
        if not self.coverage_lost:
            self._snapshot = MappingProxyType({key: entry[0] for key, entry in updated.items()})
        self.revision = revision
        return True

    def stage_record(self, item, *, session_token, revision):
        """Stage names; expose only new full keys as unnamed candidates now."""
        if not self._current(session_token, revision) or not isinstance(item, dict):
            return False
        key = item.get("public_key")
        entry = _entry(key, item)
        if entry is None:
            return False
        if key not in self._staged and len(self._staged) >= self._capacity:
            self.coverage_lost = True
            self._snapshot = MappingProxyType({})
            self.revision = revision
            return False
        if key not in self._records and not self.observe_key(key,
                session_token=session_token, revision=revision):
            return False
        self._staged[key] = (*entry, revision)
        self.revision = revision
        return True

    def merge_completed(self, payload, *, session_token, revision):
        if not self._current(session_token, revision):
            return False
        accepted = self.merge_records(payload, session_token=session_token,
                                      revision=revision, staged=True)
        self._staged = {}
        return accepted

    def observe_key(self, key, *, session_token, revision):
        if not self._current(session_token, revision) or not _key(key):
            return False
        if key in self._records:
            self.revision = revision
            return True  # An ADVERTISEMENT contains no new display name.
        return self.merge_records({key: {"adv_name": ""}},
                                  session_token=session_token, revision=revision,
                                  only_missing=True, staged=True)

    def snapshot(self):
        """One immutable version for a whole PING or multi-part PFAD build."""
        return self._snapshot
