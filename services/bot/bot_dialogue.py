"""Short terminal replies; content recognition is not sender authentication."""

from bot_identity import BOT_VERSION

CLARIFY_REPLY = ('🤖 Das habe ich nicht verstanden. Mit "Hilfe" findest du meine '
                 'Funktionen. Beste Grüße, 73.')
BOT_REPORT_REPLY = ('🤖 Kollege, hör auf, mir alles nachzuplappern – '
                    'such dir eigene Bytes 😉 73.')
PATH_HINT_REPLY = ('🤖 Meintest du „Pfad“?\n'
                   'Bitte schicke eine neue Anfrage mit „Pfad“.')
PATH_CONTEXT_REPLY = ('Ich bin ein Bot und habe nur eine Wegabfrage beantwortet. '
                      'Eine Antwort ist nicht nötig.')
VERSION_REPLY = (f'🤖 Mesh🐇Hopper\n🔖 Bot-Version {BOT_VERSION}\n'
                 '📖 Befehle: hilfe')
IDENTITY_REPLY = ('🐇 Ich bin Mesh🐇Hopper.\n'
                  'Ich teste Ping, Räume und RX-Wege. 73')
CAPABILITIES_REPLY = ('🐇 Ping/Test, Room und RX-Wege.\n'
                      'Mit „hilfe“ siehst du alle Funktionen. 73')
GREETING_REPLIES = (
    '🐇 Moin! Mesh🐇Hopper ist da.\n„hilfe“ zeigt die Befehle. 73',
    '🐇 Gude! Bereit zum Hoppeln.\n„hilfe“ zeigt die Befehle. 73',
    '🐇 Grüß dich! Mesh🐇Hopper hört zu.\nMit „hilfe“ geht’s weiter. 73',
)

COURTESY_REPLIES = (
    '🤖 Gern geschehen ✌🏻, 73',
    '🤖 Gerne wieder 🐇, 73',
    '🤖 Vielen Dank, dass Sie mit MeshHopper gehopst sind 🐇, 73',
)


def courtesy_reply(request_tag: str | None = None) -> str:
    """Stable per request, no random source, global counter or persisted state.

    No tag preserves the original static/legacy compatibility response.
    The tag is already derived from the unchanged incoming request identity.
    """
    if request_tag is None:
        return COURTESY_REPLIES[0]
    if (not isinstance(request_tag, str) or len(request_tag) != 16
            or any(char not in '0123456789abcdef' for char in request_tag)):
        raise ValueError('Invalid courtesy request tag')
    return COURTESY_REPLIES[int(request_tag, 16) % len(COURTESY_REPLIES)]


def greeting_reply(request_tag: str | None = None) -> str:
    """Stable greeting variant selected from the unchanged request identity."""
    if request_tag is None:
        return GREETING_REPLIES[0]
    if (not isinstance(request_tag, str) or len(request_tag) != 16
            or any(char not in '0123456789abcdef' for char in request_tag)):
        raise ValueError('Invalid greeting request tag')
    return GREETING_REPLIES[int(request_tag, 16) % len(GREETING_REPLIES)]

# If another station addresses us with an exact copy of a notice, stop here.
# This is not a universal loop guarantee for arbitrary foreign bot software.
TERMINAL_REPLY_BODIES = frozenset(text.casefold() for text in (
    CLARIFY_REPLY, BOT_REPORT_REPLY, PATH_HINT_REPLY, PATH_CONTEXT_REPLY,
    VERSION_REPLY, IDENTITY_REPLY, CAPABILITIES_REPLY,
    *GREETING_REPLIES, *COURTESY_REPLIES))
