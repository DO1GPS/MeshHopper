"""Complete, ASCII-only command grammar; never changes request identity."""
import re

from bot_identity import KNOWN_BOT_ALIASES


EDGE_PADDING = "\x00 \t\r\n.,!?;:"
COMMAND = re.compile(
    r"#?(ping|reping|test|retest|room)"
    r"(?:[ \t]+(ping|reping|test|retest))?"
    r"(?:[ \t]+[0-9]{1,6})?",
    re.IGNORECASE | re.ASCII,
)
FAMILIES = {"ping": "ping", "reping": "ping", "test": "test",
            "retest": "test", "room": "room"}
THANKS = re.compile(r"(?:@MeshHopper[ \t]+)?(?:danke|thanks)(?:[ \t]+73)?",
                    re.IGNORECASE | re.ASCII)
BOT_SENDERS = frozenset(alias.casefold() for alias in KNOWN_BOT_ALIASES)


def _control_inside(text: str) -> bool:
    return any((ord(char) < 32 and char != "\t") or 127 <= ord(char) <= 159
               for char in text)


def parse_command(text: object, *, wire: bool = False) -> str | None:
    """Return one canonical reply family, not a repeat count or rewritten text.

    Only received group-wire text has an unverified ``sender: `` prefix.
    Locally typed outgoing bodies must never be reinterpreted as that prefix.
    The optional ASCII number is an opaque marker; mixed ping/test is one test.
    One optional hash belongs directly before the first command token only.
    """
    if not isinstance(text, str):
        return None
    sender = None
    if wire and ": " in text:
        # Legacy sender metadata is not a new command-body policy.
        sender, text = text.split(": ", 1)
    # Thanks has its own exact forms, without the ping/test edge punctuation,
    # arbitrary numeric markers or self-replies from known bot display names.
    if THANKS.fullmatch(text.strip(" \t")):
        if sender is not None and ("\0" in sender or sender.strip().casefold() in BOT_SENDERS):
            return None  # NUL cannot form a valid original request identity.
        return "thanks"
    body = text.strip(EDGE_PADDING)
    if _control_inside(body):
        return None
    match = COMMAND.fullmatch(body)
    if match is None:
        return None
    first = FAMILIES[match[1].lower()]
    second = FAMILIES[match[2].lower()] if match[2] else None
    if second is not None:
        return "test" if {first, second} == {"ping", "test"} else None
    return first
