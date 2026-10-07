"""Complete, ASCII-only command grammar; never changes request identity."""
import re


EDGE_PADDING = "\x00 \t\r\n.,!?;:"
COMMAND = re.compile(
    r"(ping|reping|test|retest|room)"
    r"(?:[ \t]+(ping|reping|test|retest))?"
    r"(?:[ \t]+[0-9]{1,6})?",
    re.IGNORECASE | re.ASCII,
)
FAMILIES = {"ping": "ping", "reping": "ping", "test": "test",
            "retest": "test", "room": "room"}


def _control_inside(text: str) -> bool:
    return any((ord(char) < 32 and char != "\t") or 127 <= ord(char) <= 159
               for char in text)


def parse_command(text: object, *, wire: bool = False) -> str | None:
    """Return one canonical reply family, not a repeat count or rewritten text.

    Only received group-wire text has an unverified ``sender: `` prefix.
    Locally typed outgoing bodies must never be reinterpreted as that prefix.
    The optional ASCII number is an opaque marker; mixed ping/test is one test.
    """
    if not isinstance(text, str):
        return None
    if wire and ": " in text:
        # Legacy sender metadata is not a new command-body policy.
        text = text.split(": ", 1)[1]
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
