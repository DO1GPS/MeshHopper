"""Bounded display-only geographic path hypothesis, never reception evidence.

All positions retain their captured prefix/order. A whole-chain shortest-distance
ranking is not RF adjacency, authentication or a calibrated probability. No I/O,
new timer, persistent learning, device call or packet mutation.
"""
from dataclasses import dataclass, replace
import math
from collections.abc import Mapping


MAX_CANDIDATES = 64
MAX_TRANSITIONS = 65536


@dataclass(frozen=True)
class RouteContext:
    role: int | None
    position: tuple[float, float] | None


def valid_position(lat, lon):
    if (type(lat) in (int, float) and type(lon) in (int, float)
            and math.isfinite(lat) and math.isfinite(lon)
            and -90 <= lat <= 90 and -180 <= lon <= 180 and (lat != 0 or lon != 0)):
        return float(lat), float(lon)
    return None


def contact_context(record):
    role = record.get('type')
    return RouteContext(role if type(role) is int and role in (1, 2, 3) else None,
                        valid_position(record.get('adv_lat'), record.get('adv_lon')))


def _position(value):
    return valid_position(*value) if isinstance(value, tuple) and len(value) == 2 else None


def locator_position(locator):
    """Centre of the configured six-character station locator, not measured GPS."""
    if (not isinstance(locator, str) or len(locator) != 6
            or any(c not in 'ABCDEFGHIJKLMNOPQR' for c in locator[:2])
            or any(c not in '0123456789' for c in locator[2:4])
            or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWX' for c in locator[4:])):
        raise ValueError('Invalid monitor locator')
    lon = -180 + (ord(locator[0])-65)*20 + int(locator[2])*2 + (ord(locator[4])-65)/12 + 1/24
    lat = -90 + (ord(locator[1])-65)*10 + int(locator[3]) + (ord(locator[5])-65)/24 + 1/48
    return lat, lon


def distance(first, second):
    lat1, lon1 = map(math.radians, first)
    lat2, lon2 = map(math.radians, second)
    value = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 6371.0088 * 2 * math.asin(math.sqrt(max(0, min(1, value))))


def infer_path(hops, names, context, receiver):
    """Return separate display hops; unresolved/tied/incomplete context stays raw.

    Dynamic programming retains the two cheapest complete alternatives per node;
    unlike independent nearest-node selection it ranks the entire ordered chain.
    No hard RF-distance cutoff. Repeated positions are not collapsed.
    """
    original = tuple(hops)
    if not original or not any(h.status == 'ambiguous' for h in original):
        return original
    if (len(original) > 64 or not isinstance(context, Mapping)
            or not isinstance(names, Mapping) or len(names) > 4096
            or set(names) != set(context) or _position(receiver) is None):
        return original
    if any(not isinstance(key, str) or len(key) != 64
           or any(c not in '0123456789abcdef' for c in key) for key in names):
        return original
    options = []
    for hop in original:
        if (hop.status not in ('resolved', 'ambiguous') or len(hop.hash_hex) not in (2,4,6)
                or any(c not in '0123456789abcdef' for c in hop.hash_hex)):
            return original
        matches = [key for key in names if key.startswith(hop.hash_hex)]
        if len(matches) != hop.candidates:
            return original  # Names and evidence must belong to this snapshot.
        eligible = []
        for key in matches:
            meta = context[key]
            if (not isinstance(meta, RouteContext) or type(meta.role) is not int
                    or meta.role not in (1, 2, 3)):
                return original
            # Unique hybrid/other-role candidates remain part of their captured
            # position. Only an ambiguous *repeater hypothesis* ranks role2 nodes.
            if hop.status == 'ambiguous' and meta.role != 2:
                continue
            if meta.position is None or not isinstance(names[key], str) or not names[key].strip():
                return original  # Never make a candidate disappear for absent GPS/name.
            if _position(meta.position) is None:
                return original
            eligible.append(key)
        if not eligible or len(eligible) > MAX_CANDIDATES:
            return original
        options.append(eligible)
    transitions = sum(len(a)*len(b) for a,b in zip(options, options[1:])) + len(options[-1])
    if transitions > MAX_TRANSITIONS:
        return original
    # The start is unknown; no fabricated sender GPS/prior or preferred end key.
    states = {key: [(0.0, (key,))] for key in options[0]}
    for layer in options[1:]:
        next_states = {}
        for key in layer:
            candidates = []
            for previous, paths in states.items():
                length = distance(context[previous].position, context[key].position)
                candidates.extend((cost + length, route + (key,)) for cost, route in paths)
            next_states[key] = sorted(candidates)[:2]
        states = next_states
    finished = sorted((cost + distance(context[key].position, receiver), route)
                      for key, paths in states.items() for cost, route in paths)
    if not finished or len(finished) > 1 and math.isclose(finished[0][0], finished[1][0], rel_tol=1e-9, abs_tol=1e-6):
        return original
    selected = finished[0][1]
    return tuple(replace(hop, status='inferred', name=names[key]) if hop.status == 'ambiguous' else hop
                 for hop, key in zip(original, selected))
