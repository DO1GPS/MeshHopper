"""Generic display names and the existing group-text byte limits.

Display aliases are not new cryptographic station identities. The public
draft contains no operator-specific station names or location defaults.
"""
BOT_NAME = "MeshHopper"
LEGACY_BOT_NAME = "MeshHopper Monitor"
KNOWN_BOT_ALIASES = frozenset({LEGACY_BOT_NAME, BOT_NAME})

# group_packet allows 155 UTF-8 bytes for '<alias>: <body>', not 155 characters.
# Keep the existing formatter ceiling as well; never slice encoded text.
BOT_BODY_BUDGET = min(139, 155 - len(BOT_NAME.encode("utf-8")) - 2)
