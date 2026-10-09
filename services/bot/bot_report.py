"""Compact RX report from the first validated copy, never a return-path claim."""
from collections import Counter
import os
import re
import unicodedata

from reception_evidence import EvidenceResult, resolve_path


REGIONAL_NAME = re.compile(r"DE-[A-Z]{2}-[A-Z0-9]{1,4}-(.+)", re.ASCII | re.IGNORECASE)
THANKS_REPLY = "🤖 Gern geschehen ✌🏻, 73"
# Locally configured monitor QTH, never the sender's GPS or a private default.
MONITOR_QTH = os.environ.get("MESHCORE_MONITOR_QTH", "nicht gesetzt")
PATH_ARROW = "→"


def _label(value):
    if not isinstance(value, str):
        return "?"
    # Labels are display metadata, never verified station identities.
    return " ".join("".join(c for c in value
        if unicodedata.category(c) not in {"Cc", "Cf", "Cs"} and c not in "[]|<>").split()) or "?"


def _regional_short(label):
    match = REGIONAL_NAME.fullmatch(label)
    return match.group(1) if match else label


def _display_key(label):
    # Canonical Unicode equivalence only for collision checks. Never rewrite
    # evidence, request identities or the actual displayed contact strings.
    return unicodedata.normalize("NFC", label).casefold()


def _path_labels(hops, contacts):
    # Use the same valid, canonical public-key snapshot as resolve_path.
    # Display uniqueness is not authentication of the RF path or node.
    known = {key.lower(): _label(name) for key, name in contacts.items()
             if isinstance(key, str) and len(key) == 64 and isinstance(name, str)
             and all(c in "0123456789abcdefABCDEF" for c in key)}
    counts = Counter(_display_key(_regional_short(name)) for name in known.values())
    labels = []
    for hop in hops:
        if hop.status != "resolved":
            labels.append(hop.hash_hex + "?")
            continue
        full = _label(hop.name)
        short = _regional_short(full)
        labels.append(short if counts[_display_key(short)] == 1 else full)
    return labels


def _short_label(label, max_bytes):
    """Visible shortening at UTF-8 character boundaries, never packet slicing."""
    if len(label.encode("utf-8", "strict")) <= max_bytes:
        return label
    marker = "…"
    remaining = max_bytes - len(marker.encode("utf-8"))
    if remaining < 0:
        return None
    prefix = []
    for char in label:
        size = len(char.encode("utf-8", "strict"))
        if size > remaining:
            break
        prefix.append(char)
        remaining -= size
    return "".join(prefix) + marker


def response_body(command: str, evidence: EvidenceResult, contacts: dict,
                  scope_name: str | None, budget: int = 139, *,
                  original_sender: str | None = None, request_tag: str | None = None) -> str:
    heads = {"ping": "PONG", "test": "TEST", "room": "ROOM"}
    if command not in (*heads, "thanks") or type(budget) is not int or not 1 <= budget <= 139:
        raise ValueError("Invalid report request")
    tx = "unscoped" if scope_name is None else _label(scope_name)
    tx_line = f"\nTX: {tx}"
    suffix = f"\nQTH: {_label(MONITOR_QTH)}"
    if request_tag is not None:
        if (len(request_tag) != 16 or any(c not in "0123456789abcdef" for c in request_tag)):
            raise ValueError("Invalid request tag")
        # Compatibility input only. Correlation belongs to private history;
        # the sender reserves the actual packet identity before any RF attempt.
    if command == "thanks":
        if len(THANKS_REPLY.encode("utf-8")) > budget:
            raise ValueError("Report byte budget exceeded")
        return THANKS_REPLY
    single_copy = evidence.status == "available" and len(evidence.copies) == 1
    multiple_exact_copies = (evidence.status == "ambiguous"
                             and evidence.reason == "multiple_rx_copies"
                             and len(evidence.copies) >= 2)
    if not (single_copy or multiple_exact_copies):
        state = "mehrdeutig" if evidence.status == "ambiguous" else "unbekannt"
        sender = _label(original_sender) if original_sender is not None else None
        prefix = heads[command] + (" @" if sender is not None else "")
        metrics = f"\nRX: {state}"
        missing_route = "\nWeg: nicht erfasst"
        choices = [prefix + (sender or "") + tx_line + metrics + missing_route + suffix]
        minimal_routes = [missing_route]
    else:
        # Report the first whole validated reception, never combine one
        # copy's quality with another copy's hops/path. Multiple reception
        # evidence stays ambiguous; this is not a unique/all-routes claim.
        copy = evidence.copies[0]
        sender = _label(copy.text_bytes.decode("utf-8").partition(": ")[0])
        # RSSI remains in the unchanged reception copy/store. The short RF
        # report uses SNR only, specifically for reception at our monitor.
        prefix = f"{heads[command]} @"
        metrics = f"\nRX: {copy.hops} 🐇 | SNR {copy.snr_db:+g} dB"
        head = prefix + sender + tx_line + metrics
        hops = resolve_path(copy, contacts)
        named = _path_labels(hops, contacts)
        hashes = [h.hash_hex for h in hops]
        if not hops:
            routes = ["direkt"]
        else:
            routes = [PATH_ARROW.join(named)]
            # Prefer the whole ordered chain (names, then raw hashes) over
            # an abbreviated chain; this does not change any RX evidence.
            routes.append(PATH_ARROW.join(hashes))
            if len(hops) > 2:
                routes.append(f"{named[0]}{PATH_ARROW}…{PATH_ARROW}{named[-1]}")
            if len(hops) > 2:
                routes.append(f"{hashes[0]}{PATH_ARROW}…{PATH_ARROW}{hashes[-1]}")
            # A shortened report explicitly names only the final incoming hop.
            routes.extend(("letzter " + named[-1], "letzter Hash " + hashes[-1]))
        choices = [head + "\nWeg: " + route + suffix for route in routes]
        # A visible ellipsis is an omitted route, never a direct-path claim.
        # Keep TX, RX and QTH on their own lines even at the packet limit.
        choices.append(head + "\nWeg: …" + suffix)
        # Only an otherwise unsendable report may shorten the sender. Keep
        # the final incoming hash if it fits, with explicit missing prefix.
        minimal_routes = (["\nWeg: direkt"] if not hops else
                          ["\nWeg: " + ("…" + PATH_ARROW if len(hops) > 1 else "") + hashes[-1]]) + ["\nWeg: …"]
    for text in choices:
        if len(text.encode("utf-8", "strict")) <= budget:
            return text
    if sender is not None:
        for route in minimal_routes:
            fixed = prefix + tx_line + metrics + route + suffix
            shortened = _short_label(sender, budget - len(fixed.encode("utf-8", "strict")))
            if shortened is not None:
                return prefix + shortened + tx_line + metrics + route + suffix
    raise ValueError("Report byte budget exceeded")
