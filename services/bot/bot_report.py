"""Compact RX report from the first validated copy, never a return-path claim."""
from collections import Counter
from dataclasses import replace
import os
import re
import unicodedata

from reception_evidence import EvidenceResult, InboxMetrics, resolve_path
from bot_dialogue import (CAPABILITIES_REPLY, CLARIFY_REPLY, BOT_REPORT_REPLY,
                          IDENTITY_REPLY, PATH_HINT_REPLY, PATH_CONTEXT_REPLY,
                          VERSION_REPLY, courtesy_reply, greeting_reply)
from path_inference import infer_path, locator_position


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
HELP_REPLY = ("🤖 HILFE\n📡 ping/test\n🏠 room\n📩 pfad/path/weg\n"
              "🙏 danke/73\n📖 hilfe/help/dir (#)\n🔖 version")
# Locally configured monitor QTH, never the sender's GPS or a private default.
MONITOR_QTH = os.environ.get("MESHCORE_MONITOR_QTH", "nicht gesetzt")
try:
    MONITOR_POSITION = locator_position(MONITOR_QTH.rsplit(" ", 1)[-1])
except ValueError:
    MONITOR_POSITION = None
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
    # Observed country/postcode and Kassel district spellings. These display
    # conventions do not identify a station or imply regional RF confinement.
    local = re.fullmatch(r"DE[-._ ]+(?:[0-9]{5}|KS)[-._ ]+(.+)", label, re.ASCII | re.IGNORECASE)
    if local:
        return local.group(1)
    match = REGIONAL_NAME.fullmatch(label)
    if not match:
        return label
    local = match.group(1)
    postal_site = REGIONAL_POSTAL_SITE.fullmatch(local)
    if postal_site:
        return postal_site.group(1)
    area = REGIONAL_AREA.fullmatch(local)
    return area.group(1) if area and any(c.isalpha() for c in area.group(1)) else local


def _compact_name(label, stem_chars=4):
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
        short = "".join(c for c in stem if c.isalpha())[:stem_chars]
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


def _summary_site_names(hops, contacts):
    """Drop redundant numbered place tags only in the ordinary RX summary.

    The catalogue is a local display snapshot, not proof of global uniqueness.
    Distinct known site numbers and an unnumbered peer retain their labels.
    Original contacts, path evidence and the detailed PFAD view stay untouched.
    """
    known = {key.lower(): name for key, name in contacts.items()
             if isinstance(key, str) and len(key) == 64 and isinstance(name, str)
             and all(c in "0123456789abcdefABCDEF" for c in key)}
    parsed, families = {}, {}
    for name in known.values():
        label = _label(name)
        local = unicodedata.normalize("NFC", _regional_short(label))
        if CALLSIGN.search(label):
            continue
        match = re.fullmatch(r"(.+?)[-_.\s]+(?:RPT)?([0-9]{1,2})", local, re.I)
        base = match.group(1) if match else local
        # Do not rewrite embedded numeric codes, locators or short identifiers.
        if (sum(c.isalpha() for c in base) < 4 or any(c.isdigit() for c in base)
                or any(c in base for c in (PATH_ARROW, "…", "≈"))):
            continue
        number = int(match.group(2)) if match else None
        family = _display_key(base)
        families.setdefault(family, set()).add(number)
        if match:
            parsed[name] = (base, family)
    aliases = {name: base for name, (base, family) in parsed.items()
               if len(families[family]) == 1}
    displayed_contacts = {key: aliases.get(name, name) for key, name in known.items()}
    displayed_hops = [replace(hop, name=aliases[hop.name])
                      if hop.status in {"resolved", "inferred"} and hop.name in aliases
                      else hop for hop in hops]
    return displayed_hops, displayed_contacts


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
        if hop.status not in {"resolved", "inferred"}:
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
        labels.append(("≈" if hop.status == "inferred" else "") + short)
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


def _endpoint_variants(hop, displayed):
    """Grow a known place stem; retain hypothesis/site/collision markers whole."""
    if hop.status not in {"resolved", "inferred"}:
        return [displayed]
    marker = "≈" if hop.status == "inferred" else ""
    compact, callsign = _compact_name(_label(hop.name))
    visible = displayed.removeprefix(marker)
    if callsign or not compact or not visible.startswith(compact):
        return [displayed]
    # Generated hash suffixes belong to the existing collision-safe label.
    extra = visible[len(compact):]
    variants = [displayed]
    for width in range(5, ROUTE_SUMMARY_CHARS + 1):
        grown, _ = _compact_name(_label(hop.name), width)
        label = marker + grown + extra
        if len(displayed) < len(label) <= ROUTE_SUMMARY_CHARS and label not in variants:
            variants.append(label)
    return variants


def _full_endpoint_label(hop, displayed):
    """Whole local name for a known endpoint, with its existing evidence marks."""
    if hop.status not in {"resolved", "inferred"}:
        return displayed
    marker = "≈" if hop.status == "inferred" else ""
    name = _label(hop.name)
    compact, callsign = _compact_name(name)
    visible = displayed.removeprefix(marker)
    if callsign or not compact or not visible.startswith(compact):
        return displayed
    # Retain multiword places and original site/direction tokens. The suffix
    # already added by _path_labels contains only captured collision bytes.
    full = unicodedata.normalize("NFC", _regional_short(name))
    # A contact alias must not look like an extra hop or evidence marker.
    if any(symbol in full for symbol in (PATH_ARROW, "…", "≈")):
        return displayed
    return marker + full + visible[len(compact):]


def _named_route_choices(hops, labels):
    """Spend free width on names only when the selected view has two endpoints.

    Four-position and complete short paths retain their existing preference.
    Try whole endpoint names against the enclosing UTF-8 packet budget first;
    the short iPhone text cap applies only to the existing fallback variants.
    Every shorter alternative remains available for the enclosing byte budget.
    No extra catalogue scan, route inference or radio action.
    """
    choices = _route_choices(labels)
    if len(hops) <= 2:
        return choices
    endpoints = " → ".join((labels[0], "…", labels[-1]))
    full = " → ".join((_full_endpoint_label(hops[0], labels[0]), "…",
                       _full_endpoint_label(hops[-1], labels[-1])))
    if endpoints not in choices:
        return list(dict.fromkeys(choices + [full]))
    expanded = []
    for left in _endpoint_variants(hops[0], labels[0]):
        for right in _endpoint_variants(hops[-1], labels[-1]):
            text = " → ".join((left, "…", right))
            if len(text) <= ROUTE_SUMMARY_CHARS:
                gains = len(left)-len(labels[0]), len(right)-len(labels[-1])
                # Use the available width, then share it fairly. If one extra
                # character remains, favour the final incoming station.
                expanded.append(((sum(gains), min(gains), gains[1]), text))
    expanded.sort(key=lambda item: item[0], reverse=True)
    result = []
    for choice in choices:
        result.extend([full] + [text for _, text in expanded] if choice == endpoints else [choice])
    return list(dict.fromkeys(result))


def path_response_bodies(evidence: EvidenceResult, contacts: dict,
                         max_bytes: int = 123, *, original_sender: str | None = None,
                         route_context=None) -> tuple[str, ...]:
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
        body = ("📩 RX-Weg @" + _label(original_sender) + "\nEmpfangspfad nicht erfasst"
                if original_sender is not None else "📩 RX-Weg nicht erfasst")
        if len(body.encode("utf-8")) > max_bytes:
            raise ValueError("Path byte budget exceeded")
        return (body,)
    copy = evidence.copies[0]
    sender = _label(copy.text_bytes.decode("utf-8", "strict").partition(": ")[0])
    hops = resolve_path(copy, contacts)
    hops = infer_path(hops, contacts, route_context, MONITOR_POSITION)
    lines = []
    for i, hop in enumerate(hops, 1):
        raw = f"{i:02d} → [{hop.hash_hex.upper()}]"
        if hop.status in {"resolved", "inferred"} and _label(hop.name) != "?":
            label = ("≈" if hop.status == "inferred" else "") + _label(hop.name)
            line = f"{i:02d} → " + label + f" [{hop.hash_hex.upper()}]"
            # An extra inferred label must never make an otherwise sendable
            # full path fail. Keep complete captured bytes and position instead.
            header = (f"📩 RX-Weg @{sender}"
                      + (f" · {len(hops)}/{len(hops)}" if len(hops) > 1 else "")
                      + "\n")
            if hop.status == "inferred" and len((header + line).encode("utf-8")) > max_bytes:
                line = raw + f" · {hop.candidates} Kandidaten"
        else:
            line = raw + (f" · {hop.candidates} Kandidaten" if hop.status == "ambiguous" else "")
        lines.append(line)
    lines = lines or ["direkt"]
    # The captured path contains relay prefixes only.  Do not relabel its
    # final (possibly ambiguous) prefix as our receiver; append the configured
    # local endpoint as a separate, explicit destination instead.  A compact
    # form keeps the endpoint visible even with a 31-byte sender and a small
    # caller budget.
    max_parts = len(lines) + 1
    widest_header = f"📩 RX-Weg @{sender} · {max_parts}/{max_parts}\n"
    monitor_qth = _label(MONITOR_QTH)
    endpoint = next((value for value in (
        f"🏠 Ziel → {monitor_qth}", f"🏠 {monitor_qth.split(' ', 1)[0]}",
        f"🏠{monitor_qth.split(' ', 1)[0]}")
        if len((widest_header + value).encode("utf-8")) <= max_bytes), None)
    if endpoint is None:
        raise ValueError("Path byte budget exceeded")
    lines.append(endpoint)
    # The total is part of the UTF-8 budget. Try complete partitions until
    # their advertised count matches; at most 63 captured hop positions.
    for total in range(1, len(lines) + 1):
        parts, current = [], []
        header = lambda index: (f"📩 RX-Weg @{sender}"
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
                  inbox_metrics: InboxMetrics | None = None, route_context=None) -> str:
    heads = {"ping": "🏁 PONG", "test": "🏁 TEST", "room": "ROOM"}
    if command not in (*heads, "path_hint", "thanks", "help", "greeting", "version",
                       "identity", "capabilities", "clarify", "bot_report",
                       "path_context") or type(budget) is not int or not 1 <= budget <= 139:
        raise ValueError("Invalid report request")
    # Scope remains part of the unchanged send profile, not the compact reply.
    suffix = f"\n🏠 {_label(MONITOR_QTH)}"
    if request_tag is not None:
        if (len(request_tag) != 16 or any(c not in "0123456789abcdef" for c in request_tag)):
            raise ValueError("Invalid request tag")
        # Private correlation also selects a stable courtesy variant, never
        # an RF identity. The sender still reserves the actual packet identity.
    if command in ("path_hint", "thanks", "help", "greeting", "version", "identity",
                   "capabilities", "clarify", "bot_report", "path_context"):
        body = {"path_hint": PATH_HINT_REPLY, "thanks": courtesy_reply(request_tag),
                "help": HELP_REPLY, "greeting": greeting_reply(request_tag),
                "version": VERSION_REPLY, "identity": IDENTITY_REPLY,
                "capabilities": CAPABILITIES_REPLY, "clarify": CLARIFY_REPLY,
                "bot_report": BOT_REPORT_REPLY, "path_context": PATH_CONTEXT_REPLY}[command]
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
        hops = infer_path(hops, contacts, route_context, MONITOR_POSITION)
        # Display-only aliasing happens after identity/path selection. Collision
        # suffixes are generated from captured bytes afterwards, never stripped.
        hops, summary_contacts = _summary_site_names(hops, contacts)
        named = _path_labels(hops, summary_contacts)
        hashes = [_short_hash(h.hash_hex) for h in hops]
        # Prefer named endpoints over additional hash-only positions. Both
        # display width and the enclosing UTF-8 packet budget must fit.
        # Preserve an inferred named endpoint even if both names together exceed
        # the mobile line width. Never strip ≈ to make a hypothesis look exact.
        mixed = (_named_route_choices(hops, [hashes[0], *named[1:]])
                 + _named_route_choices(hops, [*named[:-1], hashes[-1]])) if any(h.status == "inferred" for h in hops) else []
        routes = list(dict.fromkeys(_named_route_choices(hops, named) + mixed + _route_choices(hashes)))
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
