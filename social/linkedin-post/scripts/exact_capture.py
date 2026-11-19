"""Wire-only C1 capture rules. No storage, native source or scheduling authority."""
import base64
import binascii
import hashlib
import json
import re
from urllib.parse import urlsplit

PROTOCOL = "storyproof.linkedin.capture/1"
CLOCK = "linux-clock-monotonic-ns/1"
POLICY_LIMITS = dict(version="exact-capture/1", max_chunks=32, max_observations=8, max_parts=4,
                     chunk_bytes=32768, body_bytes=131072, total_bytes=1048576,
                     descriptor_bytes=2048)
LIMITS = dict(**POLICY_LIMITS, stdout_frames=35, frame_bytes=65536, stdout_bytes=2293760,
              combined_output_bytes=2293760, stderr_bytes=65536, input_bytes=65536,
              context_bytes=65536, acknowledgment_bytes=65536, depth=32)
INVOCATION = {"request_key", "policy_digest", "clock", "expires_at_monotonic_ns"}
CHILD = {"request_id", "attempt_id", "runtime_digest"}
ROUTE = {"method", "origin", "path", "action"}
CHUNK = {"sequence", "observation", "part", "descriptor", "final", "payload", "sha256"}
REASONS = {"collected", "interrupted", "source_failure", "limit", "protocol_failure", "cleanup_failure"}


def fields(value: object, expected: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("invalid capture fields")


def integer(value: object, minimum: int, maximum: int) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("invalid capture integer")


def text(value: object, pattern: str, maximum: int) -> None:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum or not re.fullmatch(pattern, value):
        raise ValueError("invalid capture text")


def decimal(value: object) -> int:
    text(value, r"[1-9][0-9]*", 20)
    number = int(value)
    if number > 2**64 - 1:
        raise ValueError("capture uint64 exceeded")
    return number


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate capture field")
        result[key] = value
    return result


def _constant(value):
    raise ValueError("nonfinite capture value")


def _depth(text: str) -> None:
    depth, quoted, escaped = 0, False, False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "{[":
            depth += 1
            if depth > LIMITS["depth"]:
                raise ValueError("capture nesting limit exceeded")
        elif char in "}]":
            depth -= 1


def decode_capture(raw: bytes) -> dict:
    """One LF-delimited frame, including delimiter in its byte allowance."""
    if (len(raw) > LIMITS["frame_bytes"] or not raw.endswith(b"\n")
            or raw.count(b"\n") != 1 or b"\r" in raw):
        raise ValueError("invalid capture framing or frame limit")
    try:
        source = raw.decode("utf-8")
        _depth(source)
        value = json.loads(source, object_pairs_hook=_unique, parse_constant=_constant)
        if not isinstance(value, dict):
            raise ValueError("capture object required")
        json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        return value
    except (UnicodeError, RecursionError, OverflowError) as error:
        raise ValueError("invalid capture JSON") from error


def encode_capture(value: dict) -> bytes:
    try:
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False,
                         separators=(",", ":")).encode("utf-8") + b"\n"
        decode_capture(raw)
        return raw
    except (UnicodeError, RecursionError, OverflowError) as error:
        raise ValueError("invalid capture JSON") from error


def route_identity(route: dict) -> tuple[str, ...]:
    text(route["method"], r"[A-Z!#$%&'*+.^_`|~0-9-]+", 16)
    text(route["action"], r"[\x20-\x7e]+", 128)
    origin, path = route["origin"], route["path"]
    text(origin, r"[\x21-\x7e]+", 256)
    parsed = urlsplit(origin)
    if (not origin.startswith("https://") or not parsed.hostname
            or parsed.username is not None or parsed.password is not None or parsed.path
            or any(char in origin for char in "?#\\")):
        raise ValueError("invalid capture origin")
    parsed.port
    if (not isinstance(path, str) or not 1 <= len(path) <= 1024
            or not path.isascii() or not path.startswith("/") or "?" in path or "#" in path):
        raise ValueError("invalid capture path")
    return tuple(route[key] for key in ("method", "origin", "path", "action"))


def policy(value: dict) -> None:
    fields(value, set(POLICY_LIMITS) | {"routes"})
    for key, expected in POLICY_LIMITS.items():
        if type(value[key]) is not type(expected) or value[key] != expected:
            raise ValueError("unsupported capture policy")
    routes = value["routes"]
    if not isinstance(routes, list) or not 1 <= len(routes) <= 8:
        raise ValueError("invalid capture routes")
    seen = set()
    for route in routes:
        fields(route, ROUTE | {"sides"})
        identity = route_identity(route)
        sides = route["sides"]
        if (not isinstance(sides, list) or not 1 <= len(sides) <= 2
                or any(side not in ("request", "response") for side in sides)
                or len(set(sides)) != len(sides) or identity in seen):
            raise ValueError("duplicate or invalid capture route/side")
        seen.add(identity)


class Prefix:
    """Bounded wire admission shared by both Python relays, never retains payloads."""

    def __init__(self, capture_policy: dict):
        policy(capture_policy)
        self.routes = {route_identity(r): tuple(r["sides"]) for r in capture_policy["routes"]}
        self.chunks = self.bodies = self.decoded_bytes = self.body_bytes = 0
        self.previous = None
        self.seen = set()

    def admit(self, value: dict) -> None:
        for key, maximum in (("sequence", 31), ("observation", 7), ("part", 3)):
            integer(value[key], 0, maximum)
        if type(value["final"]) is not bool:
            raise ValueError("capture final must be boolean")
        descriptor = value["descriptor"]
        fields(descriptor, ROUTE | {"source_request_id", "side", "status"})
        route = route_identity(descriptor)
        text(descriptor["source_request_id"], r"[\x20-\x7e]+", 128)
        if descriptor["side"] not in self.routes.get(route, ()):
            raise ValueError("capture outside approved routes")
        if descriptor["status"] is not None:
            integer(descriptor["status"], 100, 599)
            if descriptor["side"] == "request":
                raise ValueError("request status must be null")
        if len(json.dumps(descriptor, indent=2, ensure_ascii=False).encode("utf-8")) > 2048:
            raise ValueError("capture descriptor limit exceeded")
        payload = value["payload"]
        if not isinstance(payload, str) or len(payload) > 43692:
            raise ValueError("capture payload limit exceeded")
        try:
            raw = base64.b64decode(payload, validate=True)
        except (ValueError, binascii.Error) as error:
            raise ValueError("invalid capture base64") from error
        if (len(raw) > 32768 or base64.b64encode(raw).decode("ascii") != payload
                or hashlib.sha256(raw).hexdigest() != value["sha256"]):
            raise ValueError("capture payload limit or digest mismatch")
        if not raw and (not value["final"] or value["part"] != 0):
            raise ValueError("empty body requires single final chunk")
        if value["sequence"] != self.chunks:
            raise ValueError("noncontiguous capture sequence")
        new_body = self.previous is None or self.previous["final"]
        body = descriptor["source_request_id"], descriptor["side"]
        if new_body:
            if value["part"] != 0 or value["observation"] != self.bodies or body in self.seen:
                raise ValueError("duplicate or noncontiguous capture body")
        elif (value["observation"] != self.previous["observation"]
              or value["part"] != self.previous["part"] + 1
              or descriptor != self.previous["descriptor"]):
            raise ValueError("interleaved or changed capture body")
        body_bytes = (0 if new_body else self.body_bytes) + len(raw)
        if body_bytes > 131072 or self.decoded_bytes + len(raw) > 1048576:
            raise ValueError("capture decoded byte limit exceeded")
        # Only mutate the admitted prefix after every check succeeds.
        if new_body:
            self.seen.add(body)
            self.bodies += 1
        self.body_bytes = body_bytes
        self.decoded_bytes += len(raw)
        self.chunks += 1
        self.previous = {k: value[k] for k in ("final", "observation", "part", "descriptor")}

    def declaration(self, value: dict) -> None:
        for key, maximum in (("chunks", 32), ("bodies", 8), ("decoded_bytes", 1048576)):
            integer(value[key], 0, maximum)
            if value[key] != getattr(self, key):
                raise ValueError("capture declaration count mismatch")
        if (value["status"] not in ("complete", "incomplete")
                or not isinstance(value["reason"], str) or value["reason"] not in REASONS
                or (value["status"] == "complete") != (value["reason"] == "collected")
                or (value["status"] == "complete" and self.previous and not self.previous["final"])):
            raise ValueError("invalid capture declaration")
