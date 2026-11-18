"""Real pipes exercise the bounded relay without Chrome or network access."""
import os
import json
import signal
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPTS = Path(__file__).parents[1] / "social/linkedin-post/scripts"

DRIVER = r"""
import json, sys
request = json.loads(sys.stdin.buffer.readline())
print('{"disposition":"ready_to_submit"}', flush=True)
ack = sys.stdin.buffer.read()
if ack != b'{"disposition":"submit_acknowledged"}\n':
    raise ValueError("bad acknowledgment")
open(request["marker"], "w").write("effect")
print('{"disposition":"uncertain"}', flush=True)
"""

LAUNCHER = r"""
import json, sys
from process_output import run_stream
def frame(raw):
    value = json.loads(raw)
    if value == {"disposition":"ready_to_submit"}:
        return "ready"
    if value == {"disposition":"uncertain"}:
        return "terminal"
    raise ValueError("bad frame")
def ack(raw):
    if raw != b'{"disposition":"submit_acknowledged"}\n':
        raise ValueError("bad acknowledgment")
run_stream([sys.executable, "-c", sys.argv[1]],
           input=json.dumps({"marker":sys.argv[2]}).encode() + b"\n",
           upstream=sys.stdin.buffer.fileno(), downstream=sys.stdout.buffer.fileno(),
           frame=frame, acknowledgment=ack, timeout=float(sys.argv[3]), grace=.1)
"""

ACK = b'{"disposition":"submit_acknowledged"}\n'
READY = b'{"disposition":"ready_to_submit"}\n'


def launch(tmp_path, driver=DRIVER, timeout=2, launcher=LAUNCHER):
    marker = tmp_path / "effect"
    proc = subprocess.Popen(
        [sys.executable, "-c", launcher, driver, str(marker), str(timeout)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env={**os.environ, "PYTHONPATH": str(SCRIPTS)})
    return proc, marker


def finish(proc, payload=b""):
    try:
        return proc.communicate(payload, timeout=5)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate(timeout=3)


def test_ready_then_ack_and_eof_reaches_child_once(tmp_path):
    proc, marker = launch(tmp_path)
    assert proc.stdout.readline() == READY
    out, err = finish(proc, ACK)
    assert proc.returncode == 0, err.decode()
    assert out == b'{"disposition":"uncertain"}\n'
    assert marker.read_text() == "effect"


@pytest.mark.parametrize("payload", [b"", ACK + ACK, ACK + b"{", b"\xff", b"x" * 65537])
def test_invalid_ack_never_reaches_effect(tmp_path, payload):
    proc, marker = launch(tmp_path)
    assert proc.stdout.readline() == READY
    finish(proc, payload)
    assert proc.returncode != 0
    assert not marker.exists()


def test_early_ack_is_not_buffered_until_ready(tmp_path):
    proc, marker = launch(tmp_path, "import time; time.sleep(.1)\n" + DRIVER)
    finish(proc, ACK)
    assert proc.returncode != 0
    assert not marker.exists()


def test_ack_without_eof_times_out_without_effect(tmp_path):
    proc, marker = launch(tmp_path, timeout=.3)
    assert proc.stdout.readline() == READY
    proc.stdin.write(ACK)
    proc.stdin.flush()
    try:
        proc.wait(timeout=4)
    finally:
        finish(proc)
    assert proc.returncode != 0
    assert not marker.exists()


@pytest.mark.parametrize("extra", [
    b'{"disposition":"ready_to_submit"}\n',
    b"{",
    b"\xff",
])
def test_premature_child_stdout_cannot_receive_ack(tmp_path, extra):
    driver = DRIVER.replace(
        "ack = sys.stdin.buffer.read()",
        f"import os; os.write(1, {extra!r})\nack = sys.stdin.buffer.read()")
    proc, marker = launch(tmp_path, driver)
    # Coalesced trailing bytes may be rejected before ready is forwarded.
    assert proc.stdout.readline() in (READY, b"")
    finish(proc, ACK)
    assert proc.returncode != 0
    assert not marker.exists()


def test_stderr_flood_is_bounded_and_cleaned_up(tmp_path):
    proc, marker = launch(tmp_path, "import os; os.write(2, b'x' * (2 * 1024 * 1024))")
    out, err = finish(proc)
    assert proc.returncode != 0
    assert len(out) + len(err) < 65536
    assert not marker.exists()


def test_child_lost_after_ready_is_not_a_terminal(tmp_path):
    proc, marker = launch(tmp_path, "print('{\"disposition\":\"ready_to_submit\"}', flush=True)")
    assert proc.stdout.readline() == READY
    finish(proc, ACK)
    assert proc.returncode != 0
    assert not marker.exists()


@pytest.mark.parametrize("sink", ["child", "parent"])
def test_blocked_write_obeys_relay_deadline(tmp_path, sink):
    launcher = LAUNCHER
    driver = "import time; time.sleep(30)"
    if sink == "child":
        launcher = launcher.replace(
            'json.dumps({"marker":sys.argv[2]})',
            'json.dumps({"marker":sys.argv[2], "padding":"x" * 60000})')
    else:
        # Linux pipe capacity is fixed before forwarding a larger ready frame.
        launcher = "import fcntl; fcntl.fcntl(1, fcntl.F_SETPIPE_SZ, 4096)\n" + launcher
        launcher = launcher.replace('value == {"disposition":"ready_to_submit"}',
                                    'value.get("disposition") == "ready_to_submit"')
        driver = (
            "import json,sys,time\n"
            "json.loads(sys.stdin.buffer.readline())\n"
            "print(json.dumps({'disposition':'ready_to_submit','padding':'x'*60000}),flush=True)\n"
            "time.sleep(30)\n")
    proc, marker = launch(tmp_path, driver, timeout=.3, launcher=launcher)
    try:
        # Keep both upstream and downstream open without servicing either.
        proc.wait(timeout=4)
    finally:
        output, error = finish(proc)
    assert proc.returncode != 0
    assert b"relay timed out" in error
    assert not marker.exists()


@pytest.mark.parametrize("suffix", [b"{", b"\xff", b'{"disposition":"uncertain"}\n'])
def test_trailing_terminal_output_is_transport_failure_after_one_effect(tmp_path, suffix):
    driver = DRIVER.replace(
        """print('{"disposition":"uncertain"}', flush=True)""",
        f"""import os; os.write(1, b'{{"disposition":"uncertain"}}\\n' + {suffix!r})""")
    proc, marker = launch(tmp_path, driver)
    assert proc.stdout.readline() == READY
    finish(proc, ACK)
    assert proc.returncode != 0
    assert marker.read_text() == "effect"


def test_preparation_terminal_needs_no_acknowledgment(tmp_path):
    proc, marker = launch(tmp_path, """
import sys
sys.stdin.buffer.readline()
print('{"disposition":"uncertain"}', flush=True)
""")
    try:
        proc.wait(timeout=3)
    finally:
        output, error = finish(proc)
    assert proc.returncode == 0, error
    assert output == b'{"disposition":"uncertain"}\n'
    assert not marker.exists()


def test_cancel_after_ready_reaps_detached_child(tmp_path):
    driver = """
import json,os,signal,sys,time
request=json.loads(sys.stdin.buffer.readline())
signal.signal(signal.SIGTERM, signal.SIG_IGN)
open(request["marker"] + ".pid", "w").write(str(os.getpid()))
print('{"disposition":"ready_to_submit"}', flush=True)
time.sleep(30)
"""
    proc, marker = launch(tmp_path, driver)
    try:
        assert proc.stdout.readline() == READY
        pid = int(marker.with_suffix(".pid").read_text())
        proc.terminate()
        _, error = finish(proc)
        assert proc.returncode == 128 + signal.SIGTERM, error
        assert not Path(f"/proc/{pid}").exists()
        assert not marker.exists()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate(timeout=3)


def test_node_channel_real_pipes_require_eof(tmp_path):
    node = r"""
const fs = require('node:fs');
const {channel} = require(process.argv[1] + '/ws_exact_channel');
(async () => {
  const io = channel(process.stdin, process.stdout, 500);
  try {
    const ctx = await io.initial();
    const ack = {protocol:'storyproof.linkedin/1', disposition:'submit_acknowledged',
      request_id:'req',attempt_id:'attempt',request_key:'a'.repeat(64)};
    await io.ready({...ack,disposition:'ready_to_submit'});
    await io.acknowledgment(ack);
    fs.writeFileSync(ctx.marker, 'effect');
    await io.terminal({disposition:'uncertain'});
  } finally {io.close();}
})().catch(e => {console.error(e.message); process.exitCode=1;});
"""
    marker = tmp_path / "node-effect"
    proc = subprocess.Popen(["node", "-e", node, str(SCRIPTS)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    proc.stdin.write(json.dumps({"marker": str(marker)}).encode() + b"\n")
    proc.stdin.flush()
    ready = json.loads(proc.stdout.readline())
    ack = {**ready, "disposition": "submit_acknowledged"}
    proc.stdin.write(json.dumps(ack).encode() + b"\n")
    proc.stdin.flush()
    # No EOF: Node must expire without invoking its offline effect.
    try:
        proc.wait(timeout=4)
    finally:
        finish(proc)
    assert proc.returncode != 0
    assert not marker.exists()


def test_node_contracts_and_lifecycle():
    proc = subprocess.run(["node", "--test", str(Path(__file__).with_name("exact_exchange.test.cjs"))],
                          capture_output=True, timeout=20)
    assert proc.returncode == 0, proc.stdout + proc.stderr
