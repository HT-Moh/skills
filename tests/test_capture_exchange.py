"""Sibling wire conformance: no browser, fixture selection or storage authority."""
import base64
import copy
import hashlib
import json
import time
import subprocess
from pathlib import Path

import pytest

from test_exact_exchange import schedule
from test_exact_publisher import NOW
from test_exact_publisher import SCRIPTS

PROTOCOL = "storyproof.linkedin.capture/1"
CLOCK = "linux-clock-monotonic-ns/1"
POLICY = dict(version="exact-capture/1", max_chunks=32, max_observations=8, max_parts=4,
              chunk_bytes=32768, body_bytes=131072, total_bytes=1048576, descriptor_bytes=2048,
              routes=[dict(method="POST", origin="https://capture.invalid", path="/offline",
                           action="offline", sides=["request", "response"])])
COMPAT = dict(platform="linux", architecture="x64", node_version="v26.2.0",
              libuv_version="1.52.1", time_namespace_id="4026531834")


def key(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode()).hexdigest()


def envelope(request=None, **changes):
    request = request or schedule()
    return dict(protocol=PROTOCOL, kind="capture_request", request=request,
                request_key=key(request), policy=copy.deepcopy(POLICY), policy_digest=key(POLICY),
                clock=CLOCK, expires_at_monotonic_ns=str(time.monotonic_ns() + 60_000_000_000),
                compatibility=dict(COMPAT), **changes)


def wire(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"


def invocation(value):
    return {k: value[k] for k in ("request_key", "policy_digest", "clock", "expires_at_monotonic_ns")}


def frame(value, kind, **fields):
    return dict(protocol=PROTOCOL, kind=kind, **invocation(value), **fields)


def child(value):
    return {k: value["request"][k] for k in ("request_id", "attempt_id", "runtime_digest")}


def chunk(value, sequence=0, observation=0, part=0, final=True, raw=b"hello", **changes):
    descriptor = {k: v for k, v in POLICY["routes"][0].items() if k != "sides"}
    descriptor.update(source_request_id=f"source-{observation}", side="response", status=200)
    return frame(value, "capture_chunk", **child(value), **{
        "sequence": sequence, "observation": observation, "part": part, "descriptor": descriptor,
        "final": final, "payload": base64.b64encode(raw).decode(),
        "sha256": hashlib.sha256(raw).hexdigest(), **changes})


def ready(value):
    r = value["request"]
    return frame(value, "capture_ready", ready=dict(
        protocol=r["protocol"], request_id=r["request_id"], attempt_id=r["attempt_id"],
        request_key=value["request_key"], runtime_digest=r["runtime_digest"],
        disposition="ready_to_submit", evidence=dict(
            actor=dict(account_url=r["account_url"], selected_actor_key="ShareBoxactorState_Self_Self",
                       checked_count=1, source="linkedin-sdui-personal-actor-v1"),
            schedule=dict(epoch_ms=1795505400000, date=dict(day=24, month=11, year=2026),
                          minutes=510, source="linkedin-confirm-schedule-post-v1"),
            browser_timezone=r["account_timezone"], text_sha256=r["text_sha256"],
            text_contract="prosemirror-paragraph-text-v1", attachments=[],
            checked_at=NOW.isoformat(), posting_at="Posting at 8:30 AM")))


def ack(value):
    return frame(value, "capture_acknowledgment", acknowledgment=dict(
        protocol=value["request"]["protocol"], request_id=value["request"]["request_id"],
        attempt_id=value["request"]["attempt_id"], request_key=value["request_key"],
        disposition="submit_acknowledged"))


def terminal(value, disposition="uncertain"):
    return frame(value, "capture_terminal", terminal=dict(
        protocol=value["request"]["protocol"], **child(value), request_key=value["request_key"],
        disposition=disposition, effect_started=False, reason="offline", checked_at=NOW.isoformat()))


def admitted():
    from exact_exchange import CaptureExchange
    value = envelope()
    exchange = CaptureExchange(value, now=NOW)
    assert exchange.frame(wire(ready(value))) == "ready"
    exchange.acknowledgment(wire(ack(value)))
    return value, exchange


def test_capture_identity_and_full_stream_counts():
    value, exchange = admitted()
    for sequence in range(32):
        assert exchange.frame(wire(chunk(value, sequence, sequence // 4, sequence % 4,
                                         final=sequence % 4 == 3, raw=b"x" * 32768))) == "chunk"
    declaration = frame(value, "capture_declaration", **child(value), status="complete",
                        reason="collected", chunks=32, bodies=8, decoded_bytes=1048576)
    assert exchange.frame(wire(declaration)) == "declaration"
    assert exchange.frame(wire(terminal(value))) == "terminal"
    assert exchange.request_key == key(value["request"])
    assert exchange.envelope == value
    exchange.envelope["policy"]["routes"].clear()
    assert exchange.envelope == value
    with pytest.raises(ValueError):
        exchange.frame(wire(chunk(value)))


@pytest.mark.parametrize("change", [
    {"sequence": True}, {"observation": False}, {"part": 1}, {"final": 1},
    {"payload": "aGVsbG9="}, {"sha256": "f" * 64}, {"extra": True},
    {"sequence": 32}, {"observation": 8}, {"part": 4},
])
def test_chunk_strictness(change):
    value, exchange = admitted()
    with pytest.raises(ValueError):
        exchange.frame(wire(chunk(value, **change)))


def test_prefix_route_body_and_declaration_admission():
    value, exchange = admitted()
    first = chunk(value, final=False)
    exchange.frame(wire(first))
    for bad in (chunk(value, sequence=1, part=1, observation=1),
                chunk(value, sequence=1, part=1, descriptor={**first["descriptor"], "status": 201}),
                frame(value, "capture_declaration", **child(value), status="complete",
                      reason="collected", chunks=1, bodies=1, decoded_bytes=5)):
        with pytest.raises(ValueError):
            exchange.frame(wire(bad))
    assert exchange.frame(wire(frame(value, "capture_declaration", **child(value),
                                    status="incomplete", reason="source_failure",
                                    chunks=1, bodies=1, decoded_bytes=5))) == "declaration"
    exchange.frame(wire(terminal(value)))


@pytest.mark.parametrize("field,replacement", [
    ("clock", "wall"), ("request_key", "f" * 64), ("policy_digest", "f" * 64),
    ("expires_at_monotonic_ns", "01"), ("expires_at_monotonic_ns", True),
    ("expires_at_monotonic_ns", "18446744073709551616"),
    ("expires_at_monotonic_ns", "1"),
    ("compatibility", {**COMPAT, "node_version": "v22.0.0"}),
])
def test_request_binding_and_clock_refuse(field, replacement):
    from exact_exchange import CaptureExchange
    value = envelope()
    value[field] = replacement
    with pytest.raises(ValueError):
        CaptureExchange(value, now=NOW)


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(max_chunks=True), lambda p: p.update(chunk_bytes=32769),
    lambda p: p.update(extra=True), lambda p: p.pop("descriptor_bytes"),
    lambda p: p["routes"].append(p["routes"][0]),
    lambda p: p["routes"][0].update(sides=["response", "response"]),
    lambda p: p["routes"][0].update(origin="https://user@capture.invalid"),
])
def test_policy_complete_strict_schema(mutation):
    from exact_exchange import CaptureExchange
    value = envelope()
    mutation(value["policy"])
    value["policy_digest"] = key(value["policy"])
    with pytest.raises(ValueError):
        CaptureExchange(value, now=NOW)


@pytest.mark.parametrize("raw", [
    b'{}\r\n', b'{"x":1,"x":1}\n', b'{"x":{"y":1,"y":1}}\n',
    b'{"x":1e999}\n', b'{"x":NaN}\n', b'{"x":"\\ud800"}\n', b'{"\\ud800":1}\n',
    b'\xff\n', b'{}\n{}\n',
])
def test_capture_decoding_refuses_ambiguous_json(raw):
    from exact_capture import decode_capture
    with pytest.raises(ValueError):
        decode_capture(raw)


def test_depth_and_inclusive_frame_limit():
    from exact_capture import decode_capture
    raw = b'{"x":' * 31 + b'{"text":"{[}"}' + b"}" * 31 + b"\n"
    assert decode_capture(raw)
    with pytest.raises(ValueError):
        decode_capture(b'{"x":' + raw[:-1] + b"}\n")
    assert decode_capture(b'{"x":"' + b"x" * (65536 - 9) + b'"}\n')
    with pytest.raises(ValueError):
        decode_capture(b'{"x":"' + b"x" * (65536 - 8) + b'"}\n')


def test_pre_ready_refusal_only_and_no_frames_before_ack():
    from exact_exchange import CaptureExchange
    value = envelope()
    exchange = CaptureExchange(value, now=NOW)
    with pytest.raises(ValueError):
        exchange.frame(wire(terminal(value)))
    assert exchange.frame(wire(terminal(value, "refused_before_submit"))) == "terminal"
    exchange = CaptureExchange(value, now=NOW)
    exchange.frame(wire(ready(value)))
    with pytest.raises(ValueError):
        exchange.frame(wire(chunk(value)))
    with pytest.raises(ValueError):
        exchange.acknowledgment(wire({**ack(value), "policy_digest": "f" * 64}))


def test_node_capture_contract_and_lifecycle():
    result = subprocess.run(["node", "--test", str(Path(__file__).with_name("capture_exchange.test.cjs"))],
                            capture_output=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


def test_cross_language_policy_identity_and_prefix_vectors():
    vectors = []
    for text in ('Écriture 🙂\n', '"quotes"\\backslash\n', "unicode \u2028line"):
        request = schedule(text=text, text_sha256=hashlib.sha256(text.encode()).hexdigest())
        value = envelope(request)
        vectors.append(dict(envelope=value, request_json=json.dumps(request, ensure_ascii=False,
                            sort_keys=True, separators=(",", ":")),
                            chunks=[chunk(value)], declaration=dict(status="complete", reason="collected",
                                                                    chunks=1, bodies=1, decoded_bytes=5)))
    source = """
const fs=require('node:fs'), c=require(process.argv[1]+'/ws_exact_capture');
const {canonical}=require(process.argv[1]+'/ws_exact_exchange');
const vectors=JSON.parse(fs.readFileSync(0,'utf8'));
for(const v of vectors) {
  const e=c.captureIdentity({...v.envelope,request_json:v.request_json});
  if(canonical(e.policy)!==canonical(v.envelope.policy)) throw Error('policy changed');
  const p=new c.Prefix(e.policy); for(const chunk of v.chunks) p.admit(chunk);
  p.declaration(v.declaration);
}
console.log(JSON.stringify(c.LIMITS));
"""
    result = subprocess.run(["node", "-e", source, str(SCRIPTS)], input=json.dumps(vectors).encode(),
                            capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    from exact_capture import LIMITS
    assert json.loads(result.stdout) == LIMITS


@pytest.mark.parametrize("change", [
    {"descriptor": {**chunk(envelope())["descriptor"], "side": "request", "status": 200}},
    {"descriptor": {**chunk(envelope())["descriptor"], "origin": "https://foreign.invalid"}},
    {"descriptor": {**chunk(envelope())["descriptor"], "status": True}},
    {"payload": "", "sha256": hashlib.sha256(b"").hexdigest(), "final": False},
    {"payload": base64.b64encode(b"x"*32769).decode(), "sha256": hashlib.sha256(b"x"*32769).hexdigest()},
])
def test_c1_descriptor_empty_and_decoded_byte_rules(change):
    value, exchange = admitted()
    with pytest.raises(ValueError):
        exchange.frame(wire(chunk(value, **change)))


def test_declaration_count_and_empty_complete_contract():
    value, exchange = admitted()
    declaration = frame(value, "capture_declaration", **child(value), status="complete",
                        reason="collected", chunks=0, bodies=0, decoded_bytes=0)
    for change in ({"chunks": True}, {"bodies": 1}, {"reason": "interrupted"},
                   {"status": "incomplete"}, {"decoded_bytes": 1}, {"unknown": 1},
                   {"reason": {}}, {"reason": []}):
        with pytest.raises(ValueError):
            exchange.frame(wire({**declaration, **change}))
    assert exchange.frame(wire(declaration)) == "declaration"
    assert exchange.frame(wire(terminal(value))) == "terminal"


def test_route_order_and_side_order_are_identity_not_normalization():
    from exact_exchange import CaptureExchange
    value = envelope()
    value["policy"]["routes"].append({**copy.deepcopy(POLICY["routes"][0]), "path": "/second"})
    value["policy_digest"] = key(value["policy"])
    CaptureExchange(value, now=NOW)
    value["policy"]["routes"].reverse()
    with pytest.raises(ValueError, match="identity"):
        CaptureExchange(value, now=NOW)
    value["policy_digest"] = key(value["policy"])
    CaptureExchange(value, now=NOW)
    value["policy"]["routes"][0]["sides"].reverse()
    with pytest.raises(ValueError, match="identity"):
        CaptureExchange(value, now=NOW)


@pytest.mark.parametrize("origin", [
    "https://host%zz", "https://[v1.future]", "https://[fe80::1%scope]", "https://host:",
])
def test_node_origin_admission_matches_c1_literal_host_contract(origin):
    from exact_capture import policy
    value = copy.deepcopy(POLICY)
    value["routes"][0]["origin"] = origin
    policy(value)
    result = subprocess.run(["node", "-e",
        "new(require(process.argv[1]+'/ws_exact_capture').Prefix)(JSON.parse(process.argv[2]));",
        str(SCRIPTS), json.dumps(value)], capture_output=True, timeout=5)
    assert result.returncode == 0, result.stderr


def test_frozen_wire_fields_limits_and_cross_language_canonical_vector():
    from exact_capture import LIMITS, INVOCATION, CHILD
    fixture = json.loads(Path(__file__).with_name("fixtures").joinpath("capture_wire_v1.json").read_text())
    assert fixture["limits"] == LIMITS
    assert set(fixture["invocation_fields"]) == INVOCATION
    assert set(fixture["child_fields"]) == CHILD
    assert fixture["policy_digest"] == key(POLICY)
    vector = fixture["canonical_vector"]
    assert vector["sha256"] == key(vector["value"])
    result = subprocess.run(["node", "-e",
        "const c=require(process.argv[1]+'/ws_exact_exchange');"
        "console.log(require('node:crypto').createHash('sha256')"
        ".update(c.canonical(JSON.parse(process.argv[2]))).digest('hex'));",
        str(SCRIPTS), json.dumps(vector["value"])], capture_output=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().decode() == vector["sha256"]
