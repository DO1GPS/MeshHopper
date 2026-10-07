"""Explain command recognition offline: no SDK, socket, radio or data store."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "bot"))
from bot_commands import parse_command  # noqa: E402

EXAMPLES = ("ping", "ReTest", "room", "ping test", "ping 123", "bitte ping mich")


def main(arguments=None):
    messages = sys.argv[1:] if arguments is None else arguments
    for text in messages or EXAMPLES:
        command = parse_command(text)
        result = {"ping": "PONG", "test": "TEST", "room": "ROOM"}.get(command, "keine Antwort")
        print(f"{text!r} -> {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
