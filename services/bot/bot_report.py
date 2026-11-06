"""Compact RX report from the first validated copy, never a return-path claim."""
from collections import Counter
import os
import re
import unicodedata

from reception_evidence import EvidenceResult, InboxMetrics, resolve_path


# Display conventions, not geography or identity checks. Remove the known
# country/state prefix first. A county/code is optional; do not discard an
# arbitrary long, mixed-case or device-like local token as though it were one.
REGIONAL_NAME = re.compile(
    r"DE[-._ ]+(?:BW|BY|BE|BB|HB|HH|HE|MV|NI|NW|RP|RLP|SL|SN|ST|SH|TH)"
    r"[-._ ]+(.+)", re.ASCII | re.IGNORECASE)
REGIONAL_AREA = re.compile(r"(?:[A-Z]{1,3}|[A-Z]{3}[0-9]R)#?[-._ ]+(.+)", re.ASCII)
REGIONAL_POSTAL_SITE = re.compile(r"[0-9]{5}[-._ ]+RPT[-._ ]+(.+)", re.ASCII | re.IGNORECASE)
# Conservative display recognition, not a licence or identity check. Numeric
# locators and raw hex prefixes must not be mistaken for station callsigns.
CALLSIGN = re.compile(r"(?<![A-Z0-9])(?:[A-Z]{1,2}|[0-9][A-Z])[0-9][A-Z]{1,4}(?![A-Z0-9])", re.ASCII | re.IGNORECASE)
DIRECTIONS = {"nord": "N", "süd": "S", "sued": "S", "ost": "O", "west": "W",
              **{direction.casefold(): direction for direction in ("N", "S", "O", "W", "NO", "NW", "SO", "SW")}}
THANKS_REPLY = "🤖 Gern geschehen ✌🏻, 73"
HELP_REPLY = ("🤖 HILFE\n📡 ping · test\n🏠 room\n📩 pfad → Weg\n"
              '🙏 danke → 73\n📖 hilfe/help/dir (auch "#")')
# Locally configured monitor QTH, never the sender's GPS or a private default.
MONITOR_QTH = os.environ.get("MESHCORE_MONITOR_QTH", "nicht gesetzt")
PATH_ARROW = "→"
# Text cap for the compact iPhone summary, not a pixel/font guarantee.
ROUTE_SUMMARY_CHARS = 22


def _label(value):
    if not isinstance(value, str):
        return "?"
    # Labels are display metadata, never verified station identities.
    return " ".join("".join(c for c in value
        if unicodedata.category(c) not in {"Cc", "Cf", "Cs"} and c not in "[]|<>").split()) or "?"


def _regional_short(label):
    match = REGIONAL_NAME.fullmatch(label)
    if not match:
        return label
    local = match.group(1)
    postal_site = REGIONAL_POSTAL_SITE.fullmatch(local)
    if postal_site:
        return postal_site.group(1)
    area = REGIONAL_AREA.fullmatch(local)
    return area.group(1) if area and any(c.isalpha() for c in area.group(1)) else local


def _compact_name(label):
    """One short place stem and useful site/direction suffixes; callsigns whole."""
    # A callsign can itself occupy the regional area-code position. Check
    # before removing that prefix, so it is never mistaken for disposable text.
    call = CALLSIGN.search(label)
    if call:
        return call.group().upper(), True
    local = _regional_short(label)
    words = re.split(r"[-_.\s]+", unicodedata.normalize("NFC", local))
    start = next((i for i, word in enumerate(words) if any(c.isalpha() for c in word)), None)
    if start is None:
        return "", False
    stem, tail = words[start], words[start + 1:]
    # VFDB is the organisation; its Znn code is the useful short site marker.
    if stem.upper() == "VFDB" and tail and re.fullmatch(r"Z[0-9]{2}", tail[0], re.I | re.ASCII):
        short, tail = tail[0].upper(), tail[1:]
        attached_number = None
    elif re.fullmatch(r"[A-Z]{3}[0-9]{1,2}R", stem, re.I | re.ASCII):
        # If an observed local code has no following place, keep it rather
        # than dropping its embedded digits (e.g. HOE0R or kdg01R).
        short, attached_number = stem.upper(), None
    else:
        attached = re.fullmatch(r"(.+?)([0-9]{1,2})", stem)
        attached_number = (attached.group(2) if attached and
                           all(c.isalpha() for c in attached.group(1)) else None)
        short = "".join(c for c in stem if c.isalpha())[:4]
    suffix = attached_number
    for word in tail:
        number = re.fullmatch(r"(?:#|RPT)?([0-9]{1,2})", word, re.I | re.ASCII)
        if suffix is None:
            suffix = number.group(1) if number else DIRECTIONS.get(word.casefold())
        if suffix is not None:
            break
    return short + ("-" + suffix if suffix else ""), False


def _short_hash(value):
    # Display only. resolve_path has already used the full captured prefix;
    # two-character labels are NOT unique or authenticated station identities.
    return value[:2].upper()


def _display_key(label):
    # Canonical Unicode equivalence only for collision checks. Never rewrite
    # evidence, request identities or the actual displayed contact strings.
    return unicodedata.normalize("NFC", label).casefold()


def room_response_body(channel: int, channel_names: dict, max_bytes: int = 123) -> str:
    """Show only configured Bot channels from its queried session snapshot.

    This is not a claim about RF reachability, the flood scope or other nodes.
    Oversized names fall back to exact channel indexes, never dropped rooms.
    """
    if (type(channel) is not int or not 0 <= channel <= 255
            or not isinstance(channel_names, dict) or channel not in channel_names
            or any(type(index) is not int or not 0 <= index <= 255 for index in channel_names)
            or type(max_bytes) is not int or not 1 <= max_bytes <= 139):
        raise ValueError("Invalid room overview")
    labels = {index: _label(name) for index, name in channel_names.items()}
    counts = Counter(_display_key(name) for name in labels.values())
    labels = {index: ("Kanal " + str(index) if name == "?" else
                      name + " [" + str(index) + "]" if counts[_display_key(name)] > 1 else name)
              for index, name in labels.items()}

    def body(names):
        other = [names[index] for index in sorted(names) if index != channel]
        lines = ["🏠 ROOM", "", "📍 " + names[channel] + " · hier"]
        lines += ["✅ " + name for name in other]
        return "\n".join(lines)

    for names in (labels, {index: "Kanal " + str(index) for index in labels}):
        text = body(names)
        if len(text.encode("utf-8", "strict")) <= max_bytes:
            return text
    raise ValueError("Room byte budget exceeded")


def _path_labels(hops, contacts):
    # Use the same valid, canonical public-key snapshot as resolve_path.
    # Display uniqueness is not authentication of the RF path or node.
    known = {key.lower(): _label(name) for key, name in contacts.items()
             if isinstance(key, str) and len(key) == 64 and isinstance(name, str)
             and all(c in "0123456789abcdefABCDEF" for c in key)}
    groups = {}
    for key, name in known.items():
        groups.setdefault(_display_key(_compact_name(name)[0]), []).append(key)
    labels = []
    for hop in hops:
        if hop.status != "resolved":
            labels.append(_short_hash(hop.hash_hex))
            continue
        short, callsign = _compact_name(_label(hop.name))
        if not short:
            short = _short_hash(hop.hash_hex)
        elif not callsign and len(groups.get(_display_key(short), ())) > 1:
            # Prefer the usual one-byte suffix; expand only to bytes actually
            # captured when that suffix would collide again (AA BB / AA CC).
            # A generated suffix must not impersonate a real site-number form.
            peers = groups[_display_key(short)]
            width = next((size for size in range(2, len(hop.hash_hex) + 1, 2)
                          if sum(key.startswith(hop.hash_hex[:size]) for key in peers) == 1
                          and _display_key(short + "-" + hop.hash_hex[:size].upper()) not in groups), None)
            short = short + "-" + hop.hash_hex[:width].upper() if width else _short_hash(hop.hash_hex)
        labels.append(short)
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


def _route_choices(labels):
    """One-line summaries, at most two positions at each end.

    Omitted positions always have a visible ellipsis. Never shorten a
    callsign or rewrite the captured path; PFAD retains every position.
    """
    if not labels:
        return ["direkt"]
    positions = (list(labels) if len(labels) <= 4 else
                 [labels[0], labels[1], "…", labels[-2], labels[-1]])
    candidates = [" → ".join(positions)]
    if len(labels) > 2:
        candidates.append(" → ".join((labels[0], "…", labels[-1])))
    return list(dict.fromkeys(text for text in candidates
                             if len(text) <= ROUTE_SUMMARY_CHARS))


def _route_text(labels):
    return next(iter(_route_choices(labels)), "…")


def path_response_bodies(evidence: EvidenceResult, contacts: dict,
                         max_bytes: int = 123, *, original_sender: str | None = None) -> tuple[str, ...]:
    """Every captured hop, in order, with whole lines and numbered parts.

    Names retain the full sanitized contact label, not the compact PING policy.
    Brackets retain the entire captured
    prefix (2/4/6 hex characters), never an invented longer node identity.
    One complete first RX copy owns the series, not a mixture of routes.
    """
    if type(max_bytes) is not int or not 1 <= max_bytes <= 139:
        raise ValueError("Invalid path byte budget")
    available = evidence.status == "available" and len(evidence.copies) == 1
    repeated = (evidence.status == "ambiguous" and evidence.reason == "multiple_rx_copies"
                and len(evidence.copies) >= 2)
    if not (available or repeated):
        body = ("📩 PFAD @" + _label(original_sender) + "\nEmpfangspfad nicht erfasst"
                if original_sender is not None else "📩 Empfangspfad nicht erfasst")
        if len(body.encode("utf-8")) > max_bytes:
            raise ValueError("Path byte budget exceeded")
        return (body,)
    copy = evidence.copies[0]
    sender = _label(copy.text_bytes.decode("utf-8", "strict").partition(": ")[0])
    hops = resolve_path(copy, contacts)
    lines = [f"{i:02d} → " + (_label(hop.name) + " " if hop.status == "resolved"
                              and _label(hop.name) != "?" else "")
             + f"[{hop.hash_hex.upper()}]"
             + (f" · {hop.candidates} Kandidaten" if hop.status == "ambiguous" else "")
             for i, hop in enumerate(hops, 1)] or ["direkt"]
    # The total is part of the UTF-8 budget. Try complete partitions until
    # their advertised count matches; at most 63 captured hop positions.
    for total in range(1, len(lines) + 1):
        parts, current = [], []
        header = lambda index: (f"📩 PFAD @{sender}"
                                + (f" · {index}/{total}" if total > 1 else "") + "\n")
        for line in lines:
            prefix = header(len(parts) + 1)
            if len((prefix + "\n".join(current + [line])).encode("utf-8")) > max_bytes:
                if not current:
                    raise ValueError("Path byte budget exceeded")
                parts.append(prefix + "\n".join(current))
                current = []
                prefix = header(len(parts) + 1)
                if len((prefix + line).encode("utf-8")) > max_bytes:
                    raise ValueError("Path byte budget exceeded")
            current.append(line)
        parts.append(header(len(parts) + 1) + "\n".join(current))
        if len(parts) == total:
            return tuple(parts)
    raise ValueError("Path partition could not fit")


def response_body(command: str, evidence: EvidenceResult, contacts: dict,
                  scope_name: str | None, budget: int = 139, *,
                  original_sender: str | None = None, request_tag: str | None = None,
                  inbox_metrics: InboxMetrics | None = None) -> str:
    heads = {"ping": "🏁 PONG", "test": "🏁 TEST", "room": "ROOM"}
    if command not in (*heads, "thanks", "help") or type(budget) is not int or not 1 <= budget <= 139:
        raise ValueError("Invalid report request")
    # Scope remains part of the unchanged send profile, not the compact reply.
    suffix = f"\n🏠 {_label(MONITOR_QTH)}"
    if request_tag is not None:
        if (len(request_tag) != 16 or any(c not in "0123456789abcdef" for c in request_tag)):
            raise ValueError("Invalid request tag")
        # Compatibility input only. Correlation belongs to private history;
        # the sender reserves the actual packet identity before any RF attempt.
    if command in ("thanks", "help"):
        body = THANKS_REPLY if command == "thanks" else HELP_REPLY
        if len(body.encode("utf-8")) > budget:
            raise ValueError("Report byte budget exceeded")
        return body
    single_copy = evidence.status == "available" and len(evidence.copies) == 1
    multiple_exact_copies = (evidence.status == "ambiguous"
                             and evidence.reason == "multiple_rx_copies"
                             and len(evidence.copies) >= 2)
    if not (single_copy or multiple_exact_copies):
        state = "mehrdeutig" if evidence.status == "ambiguous" else "unbekannt"
        sender = _label(original_sender) if original_sender is not None else None
        prefix = heads[command] + (" @" if sender is not None else "")
        metrics = f"\n📡 {state}"
        # Own V3 inbox values survive a missing raw capture. They contain no
        # path identities and must never be promoted to full RX evidence.
        if evidence.status == "unavailable" and isinstance(inbox_metrics, InboxMetrics):
            metrics = f"\n📡 {inbox_metrics.hops} 🐇 | SNR {inbox_metrics.snr_db:+g} dB"
        missing_route = "\n📩 nicht erfasst"
        choices = [prefix + (sender or "") + metrics + missing_route + suffix]
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
        metrics = f"\n📡 {copy.hops} 🐇 | SNR {copy.snr_db:+g} dB"
        head = prefix + sender + metrics
        hops = resolve_path(copy, contacts)
        named = _path_labels(hops, contacts)
        hashes = [_short_hash(h.hash_hex) for h in hops]
        # Prefer named endpoints over additional hash-only positions. Both
        # display width and the enclosing UTF-8 packet budget must fit.
        routes = list(dict.fromkeys(_route_choices(named) + _route_choices(hashes)))
        choices = [head + "\n📩 " + route + suffix for route in routes]
        # A visible ellipsis is an omitted route, never a direct-path claim.
        # Keep reception, path and QTH on their own lines at the packet limit.
        choices.append(head + "\n📩 …" + suffix)
        # Only an otherwise unsendable report may shorten the sender. Keep
        # the final incoming hash if it fits, with explicit missing prefix.
        minimal_routes = (["\n📩 direkt"] if not hops else
                          ["\n📩 " + ("…" + PATH_ARROW if len(hops) > 1 else "") + hashes[-1]]) + ["\n📩 …"]
    for text in choices:
        if len(text.encode("utf-8", "strict")) <= budget:
            return text
    if sender is not None:
        for route in minimal_routes:
            fixed = prefix + metrics + route + suffix
            shortened = _short_label(sender, budget - len(fixed.encode("utf-8", "strict")))
            if shortened is not None:
                return prefix + shortened + metrics + route + suffix
    raise ValueError("Report byte budget exceeded")
