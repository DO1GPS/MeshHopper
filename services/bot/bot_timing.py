"""Bounded, fail-open *diagnostics*, never command or radio admission.

One private digest/epoch summary per verified raw-mode request. No payload,
name, contact key, channel secret or wall-clock duration is recorded. A measured
SDK send includes admission, relay, transport and the device response; it is
not a measurement of Bluetooth airtime or remote delivery.
"""
from contextlib import nullcontext
from contextvars import ContextVar
from functools import wraps
import time
import uuid


STAGES = (
    "command_claim", "send_lock_wait", "report_build", "packet_reservation",
    "packet_collision_wait", "history_before_send", "sdk_send_raw_packet",
    "history_after_send", "completion",
)
MAX_SPAN_COUNT = 256  # A normal PFAD request has at most 63 parts.
MAX_NS = (1 << 63) - 1
_CURRENT = ContextVar("bot_private_request_timing", default=None)


class _Span:
    def __init__(self, trace, name):
        self.trace, self.name, self.started = trace, name, None

    def __enter__(self):
        self.started = self.trace.read_clock()
        return self

    def __exit__(self, *exception):
        ended = self.trace.read_clock()
        if self.started is not None and ended is not None:
            self.trace.record(self.name, ended - self.started)
        return False  # Never suppress or reinterpret the operation's exception.


class RequestTiming:
    def __init__(self, request_identity, channel, epoch, emit, clock=None):
        if (type(request_identity) is not str or len(request_identity) != 64
                or any(char not in "0123456789abcdef" for char in request_identity)
                or type(channel) is not int or not 0 <= channel <= 255
                or not ((type(epoch) is int and 0 <= epoch <= MAX_NS)
                        or (type(epoch) is str and len(epoch) == 32
                            and all(char in "0123456789abcdef" for char in epoch)))):
            raise ValueError("Invalid private timing correlation")
        self.identity, self.channel, self.epoch = request_identity, channel, epoch
        self.emit, self.clock = emit, clock or time.perf_counter_ns
        self.complete, self.finished, self.spans = True, False, {}
        self.started = self.read_clock()

    def read_clock(self):
        try:
            value = self.clock()
            if type(value) is not int or not 0 <= value <= MAX_NS:
                raise ValueError("Invalid monotonic timing sample")
            return value
        except Exception:
            self.complete = False
            return None

    def record(self, name, elapsed):
        try:
            if name not in STAGES or not 0 <= elapsed <= MAX_NS:
                self.complete = False
                return
            item = self.spans.setdefault(name, {"elapsed_ns": 0, "count": 0})
            if item["count"] >= MAX_SPAN_COUNT or item["elapsed_ns"] > MAX_NS - elapsed:
                self.complete = False
                return
            item["elapsed_ns"] += elapsed
            item["count"] += 1
        except Exception:
            self.complete = False

    def finish(self, outcome="returned"):
        if self.finished:
            return
        self.finished = True
        try:
            ended = self.read_clock()
            total = None if self.started is None or ended is None else ended - self.started
            if total is None or not 0 <= total <= MAX_NS:
                total, self.complete = None, False
            # Exactly one bounded record, not one log line for each PFAD part.
            self.emit("bot_timing", request_identity=self.identity, channel=self.channel,
                      epoch=self.epoch, handler_total_ns=total, spans=self.spans,
                      measurements_complete=self.complete,
                      handler_outcome="returned" if outcome == "returned" else "raised",
                      sdk_span_scope="admission_relay_transport_device_response",
                      rf_delivery_proven=False)
        except Exception:
            pass  # Clock/log/filesystem diagnostics must not change TX behavior.


def begin_request(identity_factory, channel, epoch, emit, *, clock=None):
    """Activate only after command recognition; never retain original text."""
    try:
        if _CURRENT.get() is None:
            trace = RequestTiming(identity_factory(), channel, epoch, emit, clock)
            _CURRENT.set(trace)
    except Exception:
        pass


def new_epoch():
    """Process-restart-safe random diagnostic epoch, not an auth token."""
    try:
        return uuid.uuid4().hex
    except Exception:
        return None  # Lost diagnostics must never prevent a device session.


def span(name):
    trace = _CURRENT.get()
    return _Span(trace, name) if trace is not None else nullcontext()


class _MeasuredSendLock:
    def __init__(self, lock):
        self.lock = lock

    async def __aenter__(self):
        with span("send_lock_wait"):
            return await self.lock.__aenter__()

    async def __aexit__(self, *exception):
        return await self.lock.__aexit__(*exception)


def measured_send_lock(lock):
    return _MeasuredSendLock(lock)


def timed_handler(handler):
    @wraps(handler)
    async def wrapped(*args, **kwargs):
        token = _CURRENT.set(None)
        outcome = "raised"
        try:
            result = await handler(*args, **kwargs)
            outcome = "returned"
            return result
        finally:
            trace = _CURRENT.get()
            if trace is not None:
                trace.finish(outcome)
            _CURRENT.reset(token)
    return wrapped
