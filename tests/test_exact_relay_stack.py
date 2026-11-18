"""Supervisor → isolated worker → Node using actual relay owners and offline browser seam."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys

import pytest

from test_exact_publisher import SCRIPTS
from test_exact_exchange import schedule

NODE = r"""
const fs = require('node:fs');
const {channel} = require('./ws_exact_channel');
const {executePrepared, identity} = require('./ws_exact_exchange');
(async () => {
  const io = channel(process.stdin, process.stdout, 1500);
  try {
    const ctx = await io.initial();
    const {request:r} = identity(ctx.exact_exchange);
    const date = ctx.dateStr.split('/').map(Number);
    const evidence = {
      actor:{account_url:r.account_url, selected_actor_key:'ShareBoxactorState_Self_Self',
        checked_count:1, source:'linkedin-sdui-personal-actor-v1'},
      schedule:{epoch_ms:ctx.epoch_ms,date:{day:date[1],month:date[0],year:date[2]},minutes:510,
        source:'linkedin-confirm-schedule-post-v1'},
      browser_timezone:r.account_timezone,text_sha256:r.text_sha256,
      text_contract:'prosemirror-paragraph-text-v1',attachments:[],checked_at:new Date().toISOString(),
      posting_at:'Posting at 8:30 AM',
    };
    let alive = false;
    const terminal = await executePrepared(ctx.exact_exchange,io,async consume => {
      alive = true;
      try {
        return await consume({evidence,revalidate:async () => {
          if (!alive) throw Error('session lost');
          fs.writeFileSync(ctx.outdir+'/revalidated','yes');
        }});
      } finally {alive = false; fs.writeFileSync(ctx.outdir+'/closed','yes');}
    },async () => {
      if (!alive || !fs.existsSync(ctx.outdir+'/revalidated')) throw Error('missing revalidation');
      fs.writeFileSync(ctx.outdir+'/runtime-probe', require('./relay_probe'));
      fs.appendFileSync(ctx.outdir+'/effect','once\n');
    });
    await io.terminal(terminal);
  } finally {io.close();}
})().catch(e => {console.error(e.message);process.exitCode=1;});
"""

SUPERVISOR = """
import sys
from pathlib import Path
from exact_exchange import decode
from process_output import read_initial
from exact_protocol import relay_schedule
request = decode(read_initial(sys.stdin.buffer.fileno(), timeout=3))
relay_schedule(Path(sys.argv[1]), request, upstream=sys.stdin.buffer.fileno(),
               downstream=sys.stdout.buffer.fileno(), outdir=Path(sys.argv[2]), timeout=3)
"""


def start(tmp_path, env_overrides=None):
    runtime, outdir = tmp_path / "runtime", tmp_path / "out"
    runtime.mkdir()
    outdir.mkdir()
    for path in SCRIPTS.iterdir():
        if path.suffix in (".py", ".js"):
            shutil.copyfile(path, runtime / path.name)
    (runtime / "exact_ws_worker.js").write_text(NODE)
    (runtime / "relay_probe.js").write_text("module.exports = 'admitted';\n")
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("LINKEDIN_", "PYTHON", "NODE_"))}
    env.update(PYTHONPATH=str(SCRIPTS), BROWSERLESS_URL="http://offline.invalid", BROWSERLESS_TOKEN="offline",
               LINKEDIN_COOKIES=str(tmp_path / "cookies.json"))
    env.update(env_overrides or {})
    (tmp_path / "cookies.json").write_text("[]")
    proc = subprocess.Popen([sys.executable, "-c", SUPERVISOR, str(runtime), str(outdir)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    text = "Écriture 🙂\n"
    from exact_runtime import snapshot
    with snapshot(runtime) as (_, digest):
        pass
    request = schedule(scheduled_at="2099-11-24T07:30:00Z", text=text,
                       text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                       runtime_digest=digest)
    return proc, outdir, request


def finish(proc, ack):
    try:
        return proc.communicate(ack, timeout=8)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate(timeout=4)


def send_request(proc, request):
    proc.stdin.write(json.dumps(request).encode() + b"\n")
    proc.stdin.flush()
    raw = proc.stdout.readline()
    assert raw, proc.stderr.read().decode()
    ready = json.loads(raw)
    assert ready["disposition"] == "ready_to_submit"
    return {key: ready[key] for key in ("protocol", "request_id", "attempt_id", "request_key")} | {
        "disposition": "submit_acknowledged"}


def test_complete_private_stack_preserves_session_and_identity(tmp_path):
    proc, outdir, request = start(tmp_path)
    ack = send_request(proc, request)
    expected = json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    assert ack["request_key"] == hashlib.sha256(expected).hexdigest()
    output, error = finish(proc, json.dumps(ack).encode() + b"\n")
    assert proc.returncode == 0, error.decode()
    terminal = json.loads(output)
    assert terminal["disposition"] == "uncertain" and terminal["effect_started"] is True
    assert terminal["request_key"] == ack["request_key"]
    assert (outdir / "effect").read_text() == "once\n"
    assert (outdir / "closed").read_text() == "yes"


@pytest.mark.parametrize("kind", ["duplicate", "trailing", "wrong", "invalid_utf8", "missing"])
def test_invalid_ack_never_reaches_node_effect(tmp_path, kind):
    proc, outdir, request = start(tmp_path)
    ack = send_request(proc, request)
    raw = json.dumps(ack).encode() + b"\n"
    payload = {"duplicate": raw * 2, "trailing": raw + b"{", "wrong": raw.replace(b"attempt-1",b"attempt-2"),
               "invalid_utf8": b"\xff\n", "missing": b""}[kind]
    finish(proc, payload)
    assert proc.returncode != 0
    assert not (outdir / "effect").exists()


def test_pipelined_request_and_ack_cannot_reach_preparation(tmp_path):
    proc, outdir, request = start(tmp_path)
    finish(proc, json.dumps(request).encode() + b"\n{}\n")
    assert proc.returncode != 0
    assert not (outdir / "effect").exists()


def test_runtime_mismatch_refuses_before_preparation(tmp_path):
    proc, outdir, request = start(tmp_path)
    request["runtime_digest"] = "f" * 64
    try:
        proc.stdin.write(json.dumps(request).encode() + b"\n")
        proc.stdin.flush()
        assert proc.stdout.readline() == b""
        _, error = finish(proc, b"")
        assert proc.returncode != 0
        assert b"publisher runtime changed" in error
        assert not (outdir / "closed").exists()
        assert not (outdir / "effect").exists()
    finally:
        finish(proc, b"")


def test_source_changes_after_ready_do_not_change_executed_snapshot(tmp_path):
    proc, outdir, request = start(tmp_path)
    ack = send_request(proc, request)
    (tmp_path / "runtime" / "relay_probe.js").write_text("module.exports = 'changed';\n")
    _, error = finish(proc, json.dumps(ack).encode() + b"\n")
    assert proc.returncode == 0, error
    assert (outdir / "runtime-probe").read_text() == "admitted"


@pytest.mark.parametrize("stop", ["cancel", "missing_eof"])
def test_stack_keeps_profile_lease_until_browser_cleanup(tmp_path, stop):
    from test_exact_worker import fake_chrome, alive, clean_pids
    import local_chrome
    profile = tmp_path / "profile"
    chrome = fake_chrome(tmp_path)
    proc, outdir, request = start(tmp_path, {
        local_chrome.CHROME_ENV: str(chrome), local_chrome.PROFILE_ENV: str(profile)})
    try:
        ack = send_request(proc, request)
        pid = int((profile / "pids").read_text())
        assert alive(pid)
        with pytest.raises(ValueError, match="profile already active"):
            with local_chrome.profile_lease(profile):
                pytest.fail("active relay profile acquired")
        if stop == "cancel":
            proc.terminate()
        else:
            proc.stdin.write(json.dumps(ack).encode() + b"\n")
            proc.stdin.flush()
        proc.wait(timeout=15)
        _, error = finish(proc, b"")
        if stop == "cancel":
            assert proc.returncode == 128 + signal.SIGTERM, error
        else:
            assert proc.returncode != 0
        assert not alive(pid)
        assert not (outdir / "effect").exists()
        assert not (profile / "SingletonLock").is_symlink()
        with local_chrome.profile_lease(profile):
            pass
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate(timeout=4)
        clean_pids(profile / "pids")
