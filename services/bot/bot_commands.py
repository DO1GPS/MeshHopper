"""Complete command grammar with exact bot mentions; keeps request identity."""
import re
import unicodedata

from bot_identity import KNOWN_BOT_ALIASES
from bot_dialogue import TERMINAL_REPLY_BODIES


COMMAND_FAMILIES = frozenset({"ping", "test", "room", "path", "path_hint", "thanks",
                              "help", "greeting", "version", "identity", "capabilities",
                              "clarify", "bot_report", "path_context"})


EDGE_PADDING = "\x00 \t\r\n.,!?;:"
COMMAND = re.compile(
    r"#?(ping|reping|test|retest|room)"
    r"(?:[ \t]+(ping|reping|test|retest))?"
    r"(?:[ \t]+[0-9]{1,6})?",
    re.IGNORECASE | re.ASCII,
)
ORIGIN_COMMAND = re.compile(
    r"#?(ping|reping|test|retest)"
    r"(?:[ \t]+(ping|reping|test|retest))?"
    r"[ \t]+aus[ \t]+(.+)",
    re.IGNORECASE | re.ASCII,
)
# Origin is a bounded sender-supplied label, never an authenticated position,
# postcode lookup or scope instruction. Receipt vocabulary cannot be a place.
ORIGIN_REPORT_WORDS = frozenset({
    "empfangen", "empfang", "hops", "hop", "snr", "rssi", "pong", "route",
    "rx", "tx", "via", "über", "ueber", "nicht", "kein", "keine", "wurde",
    "wird", "mit", "danke", "thanks", "qsl", "bericht", "bot", "erfolgreich",
    "angekommen", "bitte", "ping", "reping", "test", "retest",
})
FAMILIES = {"ping": "ping", "reping": "ping", "test": "test",
            "retest": "test", "room": "room"}
_BOT_RECIPIENTS = "|".join(re.escape(alias) for alias in sorted(
    KNOWN_BOT_ALIASES | {"MeshHopper"}, key=lambda alias: (-len(alias), alias)))
# A recipient is one complete display alias, followed by ASCII spacing or end.
# Never remove arbitrary mentions or change bytes used for request identity.
DIRECTED = re.compile(
    rf"(?:@\[(?:{_BOT_RECIPIENTS})\]|@(?:{_BOT_RECIPIENTS}))"
    r"(?:[ \t]+(?P<body>.*))?",
    re.IGNORECASE | re.ASCII,
)
THANKS = re.compile(
    r"(?:danke|thanks|vielen[ \t]+dank|besten[ \t]+dank|dankesch[öÖ]n|"
    r"danke[ \t]+sch[öÖ]n|danke[ \t]+dir|danke[ \t]+euch|merci|thx|thank[ \t]+you)"
    r"(?:[ \t]+73)?[.!?]?",
    re.IGNORECASE | re.ASCII,
)
# A positive acknowledgement is a complete own-addressed body, not a keyword
# in general channel chat. Keep the existing courtesy age/claim policy.
_POSITIVE_EMOJI = (
    r"(?:(?:👍|👌|🙏|🙌|✌|🤙|🤝)\ufe0f?[🏻-🏿]?|(?:✅|😊|🙂|😎|🎉)\ufe0f?)"
)
_ACK_SEQUENCE = rf"{_POSITIVE_EMOJI}(?:[ \t]*{_POSITIVE_EMOJI}){{0,2}}"
THANKS_EMOJI = re.compile(rf"(?:{THANKS.pattern})[ \t]*{_ACK_SEQUENCE}[.!]?", THANKS.flags)
DIRECTED_ACK = re.compile(
    rf"(?:{_ACK_SEQUENCE}|(?:ok|okay|alles[ \t]+klar|passt|super|prima|perfekt|top)"
    rf"(?:[ \t]+{_ACK_SEQUENCE})?)[.!]?",
    re.IGNORECASE | re.ASCII,
)
PATH = re.compile(r"(?:#|/)?(?:pfad|path|weg|way|route)", re.IGNORECASE | re.ASCII)
# Exact complete command-like misspellings only.  Never fuzzy-match prose and
# never execute PFAD on the user's behalf: the reply asks for a fresh command.
PATH_TYPO = re.compile(r"(?:#|/)?(?:pfard|pafd|pfaad|fad|fahrt|paht|phad)",
                       re.IGNORECASE | re.ASCII)
HELP = re.compile(r"#?(?:hilfe|help|dir)", re.IGNORECASE | re.ASCII)
VERSION = re.compile(r"#?version", re.IGNORECASE | re.ASCII)
# Additional intents require an exact own mention and a complete known body.
# Unknown prose gets a short clarification, never the entire help response.
DIRECTED_GREETING = re.compile(
    r"(?:moin(?:[ \t]+moin)?|hallo|hi|hey|hello|servus|gude|ahoi|"
    r"guten[ \t]+(?:morgen|tag|abend))",
    re.IGNORECASE | re.ASCII,
)
DIRECTED_IDENTITY = re.compile(r"wer[ \t]+bist[ \t]+du", re.IGNORECASE | re.ASCII)
DIRECTED_CAPABILITIES = re.compile(r"was[ \t]+kannst[ \t]+du", re.IGNORECASE | re.ASCII)
DIRECTED_HELP = re.compile(
    r"(?:welche[ \t]+befehle[ \t]+gibt[ \t]+es|kannst[ \t]+du[ \t]+helfen)",
    re.IGNORECASE | re.ASCII,
)
# Recognizes a report format, NOT an authenticated bot or station identity.
DIRECTED_REPORT = re.compile(
    r"empfangen[ \t]+in[ \t]+[^ \t](?:[^\r\n]{0,78}[^ \t])?"
    r"[ \t]+(?:[üÜ]ber|ueber)[ \t]+(?:[0-9]|[1-5][0-9]|6[0-3])"
    r"[ \t]+Hops?[ \t]+mit[ \t]+SNR[ \t]+[+-]?[0-9]{1,3}"
    r"(?:[.,][0-9]{1,3})?[ \t]+dB\.?",
    re.IGNORECASE | re.ASCII,
)
DIRECTED_PATH_CONTEXT = re.compile(
    r"pong[ \t]+from[ \t]+(?P<origin>.+?)[.!]?",
    re.IGNORECASE | re.ASCII,
)
BOT_SENDERS = frozenset(alias.casefold() for alias in KNOWN_BOT_ALIASES | {"MeshHopper"})


def _control_inside(text: str) -> bool:
    return any((ord(char) < 32 and char != "\t") or 127 <= ord(char) <= 159
               for char in text)


def _invalid_directed_body(text: str) -> bool:
    # Directed intents cannot smuggle a second recipient, malformed mention,
    # control, invisible format or odd spacing.
    return (_control_inside(text) or any(char in "@[]" for char in text)
            or any(unicodedata.category(char) in {"Cf", "Cs"}
                   or (char.isspace() and char not in " \t") for char in text))


def _origin_label(text: str) -> bool:
    if not 1 <= len(text) <= 64:
        return False
    # Check character categories before UTF-8 encoding (surrogates included).
    if any(not (char in " \t-.'’" or unicodedata.category(char)[0] in "LM"
                or "0" <= char <= "9") for char in text):
        return False
    if len(text.encode("utf-8")) > 80:
        return False
    words = re.split(r"[ \t]+", text)
    if words[0].isascii() and words[0].isdigit():
        if len(words[0]) != 5 or not any(char != "0" for char in words[0]):
            return False
        words = words[1:]
        if not words:
            return True
    if not 1 <= len(words) <= 6:
        return False
    for word in words:
        if word.casefold().rstrip(".") in ORIGIN_REPORT_WORDS:
            return False
        # Periods permit St./a. M.; separators must join letter components.
        segments = re.split(r"[-.'’]", word[:-1] if word.endswith(".") else word)
        if any(not segment or unicodedata.category(segment[0])[0] != "L"
               or any(unicodedata.category(char)[0] not in "LM" for char in segment)
               for segment in segments):
            return False
        if word.casefold() == "de-he":
            return False  # Region spelling is not an origin/scope command.
    return True


def _directed_path_context(text: str) -> bool:
    """Recognize only a bounded addressed ``pong from …`` response body.

    This is content shape, not station or bot authentication. Runtime context
    decides whether the body belongs to our immediately preceding Weg reply.
    """
    match = DIRECTED_PATH_CONTEXT.fullmatch(text)
    if match is None:
        return False
    origin = match["origin"].strip(" \t")
    return (1 <= len(origin) <= 64 and len(origin.encode("utf-8")) <= 80
            and any(unicodedata.category(char)[0] in "LN" for char in origin)
            and all(char in " \t-.'’" or unicodedata.category(char)[0] in "LMN"
                    for char in origin))


def _body_command(text: str) -> str | None:
    if THANKS.fullmatch(text.strip(" \t")) or THANKS_EMOJI.fullmatch(text.strip(" \t")):
        return "thanks"
    body = text.strip(EDGE_PADDING)
    if _control_inside(body):
        return None
    if PATH.fullmatch(body):
        return "path"
    if PATH_TYPO.fullmatch(body):
        return "path_hint"
    if HELP.fullmatch(body):
        return "help"
    if VERSION.fullmatch(body):
        return "version"
    match = COMMAND.fullmatch(body)
    if match is None:
        if _control_inside(text):
            return None  # Do not broaden legacy edge padding to origin labels.
        match = ORIGIN_COMMAND.fullmatch(body)
        if match is None or not _origin_label(match[3]):
            return None
    first = FAMILIES[match[1].lower()]
    second = FAMILIES[match[2].lower()] if match[2] else None
    if second is not None:
        return "test" if {first, second} == {"ping", "test"} else None
    return first


def parse_command(text: object, *, wire: bool = False) -> str | None:
    """Return one family without rewriting the received text or its identity.

    Only received group-wire text has an unverified ``sender: `` prefix.
    Locally typed outgoing bodies must never be reinterpreted as that prefix.
    A complete own mention may contain a command, explicit greeting/help intent,
    report or unknown request. The latter two receive separate short notices.
    Exact terminal notices remain silent, including when addressed back to us.
    """
    if not isinstance(text, str):
        return None
    sender = None
    if wire and ": " in text:
        sender, text = text.split(": ", 1)
    directed = DIRECTED.fullmatch(text.strip(" \t"))
    if directed:
        if sender is not None and (_control_inside(sender)
                                   or sender.strip().casefold() in BOT_SENDERS):
            return None
        body = directed["body"] or ""
        if _invalid_directed_body(body):
            return None
        if body.strip(" \t").casefold() in TERMINAL_REPLY_BODIES:
            return None
        command = _body_command(body)
        if command is not None:
            return command
        if _directed_path_context(body.strip(" \t")):
            return "path_context"
        if DIRECTED_ACK.fullmatch(body.strip(" \t")):
            return "thanks"
        if DIRECTED_GREETING.fullmatch(body.strip(EDGE_PADDING)):
            return "greeting"
        if DIRECTED_IDENTITY.fullmatch(body.strip(EDGE_PADDING)):
            return "identity"
        if DIRECTED_CAPABILITIES.fullmatch(body.strip(EDGE_PADDING)):
            return "capabilities"
        if DIRECTED_HELP.fullmatch(body.strip(EDGE_PADDING)):
            return "help"
        return "bot_report" if DIRECTED_REPORT.fullmatch(body.strip(" \t")) else "clarify"
    command = _body_command(text)
    if command == "thanks" and sender is not None and (
            "\0" in sender or sender.strip().casefold() in BOT_SENDERS):
        return None
    return command
