"""Real supervisor/isolated worker/two relays/Node, replacing only offline source/preparation."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from test_exact_publisher import SCRIPTS
from test_exact_exchange import schedule
from test_capture_exchange import envelope, wire, ack

SUPERVISOR = """
import sys
from pathlib import Path
from exact_capture import decode_capture
from process_output import read_initial
from exact_protocol import relay_capture
value = decode_capture(read_initial(sys.stdin.buffer.fileno(), timeout=5))
relay_capture(Path(sys.argv[1]), value, upstream=sys.stdin.buffer.fileno(),
              downstream=sys.stdout.buffer.fileno(), outdir=Path(sys.argv[2]))
"""
PREPARATION = r"""
const fs=require('node:fs');
module.exports.withPreparedExact=async (s,consume)=>{
  const r=s.ctx,date=r.dateStr.split('/').map(Number);
  const evidence={
    actor:{account_url:r.account_url,selected_actor_key:'ShareBoxactorState_Self_Self',
      checked_count:1,source:'linkedin-sdui-personal-actor-v1'},
    schedule:{epoch_ms:r.epoch_ms,date:{day:date[1],month:date[0],year:date[2]},minutes:510,
      source:'linkedin-confirm-schedule-post-v1'},
    browser_timezone:r.account_timezone,text_sha256:r.text_sha256,
    text_contract:'prosemirror-paragraph-text-v1',attachments:[],checked_at:new Date().toISOString(),
    posting_at:'Posting at 8:30 AM'};
  try{return await consume({evidence,revalidate:async()=>{
    fs.writeFileSync(s.ctx.outdir+'/revalidated','yes');
  }});}finally{fs.writeFileSync(s.ctx.outdir+'/preparation-closed','yes');}
};
"""
SOURCE = r"""
const fs=require('node:fs'),{createHash}=require('node:crypto');
module.exports.native_capture_supported=true;
module.exports.effect=async s=>{
  if(!fs.existsSync(s.ctx.outdir+'/revalidated') || !fs.existsSync(s.ctx.outdir+'/source-ready'))
    throw Error('missing source/revalidation');
  fs.appendFileSync(s.ctx.outdir+'/effect','once\n');
  fs.writeFileSync(s.ctx.outdir+'/probe',require('./capture_probe'));
};
module.exports.withSource=async(s,emit,consume)=>{
  fs.writeFileSync(s.ctx.outdir+'/source-ready','yes');
  try{return await consume({finish:async()=>{
    for(let sequence=0;sequence<32;sequence++){
      const observation=Math.floor(sequence/4),part=sequence%4,raw=Buffer.alloc(32768,sequence);
      await emit({sequence,observation,part,final:part===3,payload:raw.toString('base64'),
        sha256:createHash('sha256').update(raw).digest('hex'),descriptor:{
          method:'POST',origin:'https://capture.invalid',path:'/offline',action:'offline',
          source_request_id:'source-'+observation,side:'response',status:200}});
    }
    return 'collected';
  }});}finally{fs.writeFileSync(s.ctx.outdir+'/source-closed','yes');}
};
"""
BROWSER = r"""
const fs=require('node:fs');
module.exports.connect=async()=>({
  newPage:async()=>({on(){},removeListener(){},setViewport:async()=>{},setCookie:async()=>{},
    goto:async()=>{},url:()=> 'https://www.linkedin.com/feed/',evaluate:async()=>{},
    close:async()=>{}}),
  disconnect:async()=>{}
});
"""


def start(tmp_path, *, source=SOURCE, browser=BROWSER, preparation=PREPARATION,
          channel_change=None, env_changes=None, seconds=60):
    runtime, outdir = tmp_path / "runtime", tmp_path / "out"
    runtime.mkdir()
    outdir.mkdir()
    for path in SCRIPTS.iterdir():
        if path.suffix in (".py", ".js"):
            shutil.copyfile(path, runtime / path.name)
    (runtime / "ws_exact_preview.js").write_text(preparation)
    (runtime / "ws_exact_capture_source.js").write_text(source)
    (runtime / "capture_probe.js").write_text("module.exports='admitted';")
    if channel_change is not None:
        target = runtime / "ws_exact_channel.js"
        target.write_text(channel_change(target.read_text()))
    puppet = runtime / "node_modules/puppeteer-core"
    puppet.mkdir(parents=True)
    (puppet / "index.js").write_text(browser)
    # Browser preparation clock wait is synthetic too; no networking/browser is available.
    page = runtime / "ws_page.js"
    page.write_text(page.read_text().replace(
        "const sleep = (ms) => new Promise((r) => setTimeout(r, ms));",
        "const sleep = async () => {};"))
    env = {k: v for k, v in os.environ.items() if not k.startswith(("LINKEDIN_", "PYTHON", "NODE_"))}
    env.update(PYTHONPATH=str(SCRIPTS), BROWSERLESS_URL="http://offline.invalid", BROWSERLESS_TOKEN="offline",
               LINKEDIN_COOKIES=str(tmp_path / "cookies.json"))
    env.update(env_changes or {})
    (tmp_path / "cookies.json").write_text(
        '[{"name":"offline","value":"fixture","domain":".capture.invalid"}]')
    from exact_runtime import snapshot
    from exact_capture_clock import observe_compatibility
    with snapshot(runtime) as (_, digest):
        pass
    text = 'Écriture 🙂 "quoted"\\line\n'
    value = envelope(schedule(scheduled_at="2099-11-24T07:30:00Z", text=text,
                              text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                              runtime_digest=digest))
    import time
    value["expires_at_monotonic_ns"] = str(time.monotonic_ns() + int(seconds * 1e9))
    value["compatibility"] = observe_compatibility()
    proc = subprocess.Popen([sys.executable, "-c", SUPERVISOR, str(runtime), str(outdir)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    return proc, outdir, value


def ready(proc, value):
    proc.stdin.write(wire(value))
    proc.stdin.flush()
    line = proc.stdout.readline()
    assert line, proc.stderr.read()
    result = json.loads(line)
    assert result["kind"] == "capture_ready"
    assert result["request_key"] == value["request_key"]
    assert result["policy_digest"] == value["policy_digest"]
    return result


def finish(proc, payload=b""):
    try:
        return proc.communicate(payload, timeout=20)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate(timeout=5)


def finish_after_observed_terminal(proc, value, release):
    """Inject a post-terminal fault only after both relays have forwarded terminal."""
    import select
    proc.stdin.write(wire(ack(value)))
    proc.stdin.close()
    proc.stdin = None
    prefix = bytearray()
    pending = bytearray()
    terminal = False
    while not terminal:
        assert select.select([proc.stdout], [], [], 5)[0], "terminal observation stalled"
        chunk = os.read(proc.stdout.fileno(), 65536)
        assert chunk, "child ended before terminal"
        prefix.extend(chunk)
        pending.extend(chunk)
        while b"\n" in pending:
            line, _, rest = pending.partition(b"\n")
            pending[:] = rest
            terminal |= json.loads(line)["kind"] == "capture_terminal"
    release.write_text("terminal observed")
    suffix, error = finish(proc)
    return bytes(prefix) + suffix, error


def test_capture_full_stack_and_runtime_mutation(tmp_path):
    proc, outdir, value = start(tmp_path)
    ready(proc, value)
    assert not (outdir / "effect").exists()
    (tmp_path / "runtime/capture_probe.js").write_text("module.exports='changed';")
    output, error = finish(proc, wire(ack(value)))
    assert proc.returncode == 0, error
    frames = [json.loads(line) for line in output.splitlines()]
    assert len(frames) == 34
    assert [f["sequence"] for f in frames[:-2]] == list(range(32))
    assert frames[-2]["status"] == "complete"
    assert frames[-2]["decoded_bytes"] == 1048576
    assert frames[-1]["terminal"]["disposition"] == "uncertain"
    assert (outdir / "effect").read_text() == "once\n"
    assert (outdir / "probe").read_text() == "admitted"
    assert (outdir / "source-closed").exists()
    assert (outdir / "preparation-closed").exists()


@pytest.mark.parametrize("change", ["policy", "trailing", "duplicate", "crlf", "missing"])
def test_capture_stack_invalid_ack_no_callback(tmp_path, change):
    proc, outdir, value = start(tmp_path)
    ready(proc, value)
    raw = wire(ack(value))
    raw = {"policy":raw.replace(value["policy_digest"].encode(),b"f"*64), "trailing":raw+b"{",
           "duplicate":raw*2, "crlf":raw[:-1]+b"\r\n", "missing":b""}[change]
    finish(proc, raw)
    assert proc.returncode != 0
    assert not (outdir / "effect").exists()


def test_incomplete_declaration_clean_exit_stays_incomplete(tmp_path):
    source = SOURCE.replace("sequence<32", "sequence<1").replace("return 'collected'", "return 'source_failure'")
    proc, outdir, value = start(tmp_path, source=source)
    ready(proc, value)
    output, error = finish(proc, wire(ack(value)))
    assert proc.returncode == 0, error
    frames = [json.loads(line) for line in output.splitlines()]
    assert frames[-2]["status"] == "incomplete"
    assert frames[-2]["bodies"] == 1
    assert (outdir / "effect").read_text() == "once\n"


def test_terminal_does_not_hide_disconnect_failure(tmp_path):
    release = tmp_path / "release-close-fault"
    proc, outdir, value = start(tmp_path, browser=BROWSER.replace(
        "disconnect:async()=>{}", "disconnect:async()=>{"
        f"while(!fs.existsSync({json.dumps(str(release))})) await new Promise(r=>setTimeout(r,5));"
        "throw Error('offline cleanup fault');}"))
    ready(proc, value)
    output, error = finish_after_observed_terminal(proc, value, release)
    assert proc.returncode != 0
    assert b'capture_terminal' in output
    assert b"offline cleanup fault" in error
    assert (outdir / "effect").read_text() == "once\n"


def test_capture_stack_uses_real_profile_lease(tmp_path):
    from test_exact_worker import fake_chrome, alive, clean_pids
    import local_chrome
    profile = tmp_path / "profile"
    chrome = fake_chrome(tmp_path)
    proc, outdir, value = start(tmp_path, env_changes={
        local_chrome.CHROME_ENV: str(chrome), local_chrome.PROFILE_ENV: str(profile)})
    try:
        ready(proc, value)
        pid = int((profile / "pids").read_text())
        with pytest.raises(ValueError, match="profile already active"):
            with local_chrome.profile_lease(profile):
                pytest.fail("profile acquired while capture active")
        _, error = finish(proc, wire(ack(value)))
        assert proc.returncode == 0, error
        assert not alive(pid)
        assert not (profile / "SingletonLock").is_symlink()
        with local_chrome.profile_lease(profile):
            pass
    finally:
        finish(proc)
        clean_pids(profile / "pids")


def test_public_capture_capabilities_and_fresh_gate(tmp_path):
    from exact_capture import PROTOCOL, LIMITS
    args = [sys.executable, str(SCRIPTS / "post_linkedin.py"), "--protocol", PROTOCOL]
    result = subprocess.run(args, input=wire(dict(protocol=PROTOCOL,
        kind="capture_capabilities_request", request_id="cap-1")), capture_output=True, timeout=40)
    assert result.returncode == 0, result.stderr
    caps = json.loads(result.stdout)
    golden = json.loads(Path(__file__).with_name("fixtures").joinpath("capture_wire_v1.json").read_text())
    assert set(caps) == set(golden["capability_fields"])
    assert set(caps["compatibility"]) == set(golden["compatibility_fields"])
    assert caps["limits"] == LIMITS
    assert caps["relay_supported"] is True
    assert caps["native_capture_supported"] is False and caps["schedule_exact"] is False
    value = envelope()
    result = subprocess.run(args, input=wire(value), capture_output=True, timeout=10,
                            env={**os.environ, "LINKEDIN_LOCAL_CHROME": "/does/not/exist"})
    assert result.returncode == 0, result.stderr
    refusal = json.loads(result.stdout)
    assert refusal["kind"] == "capture_terminal"
    assert refusal["terminal"]["disposition"] == "refused_before_submit"
    assert refusal["terminal"]["effect_started"] is False


@pytest.mark.parametrize("failure", ["source_close", "preparation_close", "page_close", "profile_release"])
def test_capture_cleanup_faults_never_attest_zero(tmp_path, failure):
    source, browser = SOURCE, BROWSER
    if failure == "source_close":
        source = source.replace("fs.writeFileSync(s.ctx.outdir+'/source-closed','yes');",
                                "throw Error('source cleanup failure');")
    if failure == "page_close":
        browser = browser.replace("close:async()=>{}", "close:async()=>{throw Error('page cleanup failure');}")
    env_changes = None
    if failure == "profile_release":
        from test_exact_worker import fake_chrome
        import local_chrome
        env_changes = {local_chrome.CHROME_ENV: str(fake_chrome(tmp_path)),
                       local_chrome.PROFILE_ENV: str(tmp_path / "profile")}
    proc, outdir, value = start(tmp_path, source=source, browser=browser, env_changes=env_changes)
    if failure in ("preparation_close", "profile_release"):
        # Must mutate before snapshot/admission; recompute exact fixture digest.
        runtime = tmp_path / "runtime"
        if failure == "preparation_close":
            target = runtime / "ws_exact_preview.js"
            target.write_text(target.read_text().replace(
                "fs.writeFileSync(s.ctx.outdir+'/preparation-closed','yes');",
                "throw Error('preparation cleanup failure');"))
        else:
            target = runtime / "profile_lease.py"
            target.write_text(target.read_text().replace(
                '                    _borrowed = False',
                '                    _borrowed = False\n'
                '                    raise CleanupError(["fixture release failure"])'))
        from exact_runtime import snapshot
        from test_capture_exchange import key
        with snapshot(runtime) as (_, digest):
            value["request"]["runtime_digest"] = digest
        value["request_key"] = key(value["request"])
    ready(proc, value)
    finish(proc, wire(ack(value)))
    assert proc.returncode != 0
    assert (outdir / "effect").read_text() == "once\n"


def test_capture_cancellation_preserves_interrupt_and_quarantines_unproven_child(tmp_path):
    from test_exact_worker import fake_chrome, alive, clean_pids
    import local_chrome
    import signal
    profile = tmp_path / "profile"
    proc, outdir, value = start(tmp_path, env_changes={
        local_chrome.CHROME_ENV: str(fake_chrome(tmp_path)), local_chrome.PROFILE_ENV: str(profile)})
    try:
        ready(proc, value)
        pid = int((profile / "pids").read_text())
        proc.terminate()
        finish(proc)
        assert proc.returncode == 128 + signal.SIGTERM
        assert not alive(pid)
        assert not (outdir / "effect").exists()
        with pytest.raises(ValueError, match="quarantined"):
            with local_chrome.profile_lease(profile):
                pass
    finally:
        finish(proc)
        clean_pids(profile / "pids")


def test_public_refusal_does_not_wait_for_acknowledgment_eof(tmp_path):
    from exact_capture import PROTOCOL
    proc = subprocess.Popen(
        [sys.executable, str(SCRIPTS / "post_linkedin.py"), "--protocol", PROTOCOL],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        proc.stdin.write(wire(envelope()))
        proc.stdin.flush()
        import select
        assert select.select([proc.stdout], [], [], 2)[0], "public refusal blocked on acknowledgment EOF"
        assert json.loads(proc.stdout.readline())["terminal"]["disposition"] == "refused_before_submit"
        _, error = finish(proc)
        assert proc.returncode == 0, error
    finally:
        finish(proc)


def test_oversized_dynamic_browser_context_refuses_before_ready(tmp_path):
    proc, outdir, value = start(tmp_path, env_changes={"BROWSERLESS_TOKEN": "x"*65536})
    proc.stdin.write(wire(value))
    proc.stdin.flush()
    assert proc.stdout.readline() == b""
    finish(proc)
    assert proc.returncode != 0
    assert not (outdir / "effect").exists()
    assert not (outdir / "source-ready").exists()


def test_hanging_post_terminal_cleanup_leaves_reap_budget(tmp_path):
    import time
    pidfile = tmp_path / "node.pid"
    browser = BROWSER.replace("disconnect:async()=>{}", "disconnect:async()=>{"
        f"fs.writeFileSync({json.dumps(str(pidfile))},String(process.pid));"
        "await new Promise(r=>setTimeout(r,60000));}")
    proc, outdir, value = start(tmp_path, browser=browser, seconds=17)
    ready(proc, value)
    output, _ = finish(proc, wire(ack(value)))
    assert proc.returncode != 0
    assert b"capture_terminal" in output
    assert time.monotonic_ns() < int(value["expires_at_monotonic_ns"]) - 4_000_000_000
    assert not Path("/proc", pidfile.read_text()).exists()
    assert (outdir / "effect").read_text() == "once\n"


@pytest.mark.parametrize("owner", ["page", "disconnect", "source", "preparation", "channel"])
def test_handle_free_unresolved_cleanup_never_attests_success(tmp_path, owner):
    """An unresolved Promise has no event-loop handle; it must still fail attestation."""
    browser, source, preparation, channel_change = BROWSER, SOURCE, PREPARATION, None
    entered = tmp_path / "cleanup-entered"
    disconnected = tmp_path / "disconnect-attempted"
    stuck = f"fs.writeFileSync({json.dumps(str(entered))},'yes');await new Promise(()=>{{}});"
    browser = browser.replace("disconnect:async()=>{}", "disconnect:async()=>{"
        f"fs.writeFileSync({json.dumps(str(disconnected))},'yes');" +
        (stuck if owner == "disconnect" else "") + "}")
    if owner == "page":
        browser = browser.replace("close:async()=>{}", "close:async()=>{" + stuck + "}")
    elif owner == "source":
        source = source.replace("fs.writeFileSync(s.ctx.outdir+'/source-closed','yes');", stuck)
    elif owner == "preparation":
        preparation = preparation.replace("fs.writeFileSync(s.ctx.outdir+'/preparation-closed','yes');", stuck)
    elif owner == "channel":
        channel_change = lambda text: text.replace("close:() => {", "close:async () => {"
            "clearTimeout(timer);require('node:fs').writeFileSync("
            + json.dumps(str(entered)) + ",'yes');await new Promise(()=>{});")
    proc, outdir, value = start(tmp_path, source=source, browser=browser, preparation=preparation,
                               channel_change=channel_change, seconds=17)
    ready(proc, value)
    output, error = finish(proc, wire(ack(value)))
    assert entered.exists(), error
    assert proc.returncode != 0, (owner, output[-1500:], error)
    if owner in ("page", "disconnect", "channel"):
        assert b"capture_terminal" in output
    assert disconnected.exists(), "independent disconnect skipped behind hung cleanup"
    assert (outdir / "effect").read_text() == "once\n"


@pytest.mark.parametrize("channel_error", [False, True])
def test_post_terminal_channel_settlement_observes_errors_not_work_cutoff(tmp_path, channel_error):
    release = tmp_path / "release-channel-fault"
    body = (f"while(!fs.existsSync({json.dumps(str(release))})) await new Promise(r=>setTimeout(r,5));"
            "process.stdout.emit('error',Error('late channel failure'));") if channel_error else \
            "await new Promise(resolve=>setTimeout(resolve,2400));"
    browser = BROWSER.replace("disconnect:async()=>{}", "disconnect:async()=>{" + body + "}")
    proc, outdir, value = start(tmp_path, browser=browser, seconds=17)
    ready(proc, value)
    output, error = finish_after_observed_terminal(proc, value, release) if channel_error else \
        finish(proc, wire(ack(value)))
    assert b"capture_terminal" in output
    if channel_error:
        assert proc.returncode != 0, (output, error)
        assert b"late channel failure" in error
    else:
        assert proc.returncode == 0, error
    assert (outdir / "effect").read_text() == "once\n"


@pytest.mark.parametrize("failure", ["source", "preparation", "invalid_ack", "early_eof", "nonzero"])
def test_failed_capture_allows_independent_cleanup_and_quarantines_profile(tmp_path, failure):
    from test_exact_worker import fake_chrome, alive, clean_pids
    from exact_runtime import snapshot
    from test_capture_exchange import key
    import local_chrome
    import time

    profile = tmp_path / "profile"
    entered, page_closed, disconnected = [tmp_path / name for name in
                                          ("cleanup-entered", "page-closed", "disconnected")]
    browser = BROWSER.replace("close:async()=>{}", "close:async()=>{"
        "await new Promise(resolve=>setTimeout(resolve,150));"
        f"fs.writeFileSync({json.dumps(str(page_closed))},'yes');" + "}")
    browser = browser.replace("disconnect:async()=>{}", "disconnect:async()=>{"
        f"fs.writeFileSync({json.dumps(str(disconnected))},'yes');" + "}")
    source, preparation = SOURCE, PREPARATION
    stuck = f"fs.writeFileSync({json.dumps(str(entered))},'yes');await new Promise(()=>{{}});"
    if failure == "source":
        source = source.replace("fs.writeFileSync(s.ctx.outdir+'/source-closed','yes');", stuck)
    elif failure == "preparation":
        preparation = preparation.replace("fs.writeFileSync(s.ctx.outdir+'/preparation-closed','yes');", stuck)
    elif failure in ("early_eof", "nonzero"):
        source = source.replace("fs.writeFileSync(s.ctx.outdir+'/source-closed','yes');",
                                "process.exit(" + ("0" if failure == "early_eof" else "7") + ");")
    proc, outdir, value = start(tmp_path, source=source, preparation=preparation, browser=browser,
        seconds=17, env_changes={local_chrome.CHROME_ENV: str(fake_chrome(tmp_path)),
                                 local_chrome.PROFILE_ENV: str(profile)})
    # Record actual borrowed-worker quarantine before supervisor independently unwinds.
    borrowed_marker = tmp_path / "borrowed-quarantine"
    target = tmp_path / "runtime/profile_lease.py"
    target.write_text(target.read_text().replace("    def quarantine(self, error):",
        "    def quarantine(self, error):\n"
        f"        if self.borrowed: Path({str(borrowed_marker)!r}).write_text(str(error))"))
    with snapshot(tmp_path / "runtime") as (_, digest):
        value["request"]["runtime_digest"] = digest
    value["request_key"] = key(value["request"])
    try:
        ready(proc, value)
        pid = int((profile / "pids").read_text())
        output, error = finish(proc, b"{}\n" if failure == "invalid_ack" else wire(ack(value)))
        assert proc.returncode != 0, error
        assert not alive(pid)
        assert time.monotonic_ns() < int(value["expires_at_monotonic_ns"])
        if failure in ("source", "preparation", "invalid_ack"):
            assert page_closed.exists(), "page cleanup preempted by outer relay"
            assert disconnected.exists(), "disconnect skipped after pre-terminal failure"
        if failure in ("source", "preparation"):
            assert entered.exists()
        assert b"capture_terminal" not in output
        assert borrowed_marker.exists(), "worker lost unknown cleanup before inherited lease boundary"
        assert b'"quarantined": true' in (profile / ".linkedin-poster.lease").read_bytes()
        with pytest.raises(ValueError, match="quarantined"):
            with local_chrome.profile_lease(profile):
                pass
        if failure == "invalid_ack":
            assert not (outdir / "effect").exists()
        else:
            assert (outdir / "effect").read_text() == "once\n"
    finally:
        finish(proc)
        clean_pids(profile / "pids")


@pytest.mark.parametrize("pending", ["authentication", "preparation"])
def test_early_eof_interrupts_pending_setup_for_independent_cleanup(tmp_path, pending):
    from test_exact_worker import fake_chrome, clean_pids
    from test_process_lifecycle import wait_ready
    import local_chrome
    import time

    entered, closed, disconnected = [tmp_path / name for name in ("entered", "closed", "disconnected")]
    stuck = f"fs.writeFileSync({json.dumps(str(entered))},'yes');await new Promise(()=>{{}});"
    browser = BROWSER.replace("close:async()=>{}", "close:async()=>{"
        f"fs.writeFileSync({json.dumps(str(closed))},'yes');" + "}")
    browser = browser.replace("disconnect:async()=>{}", "disconnect:async()=>{"
        f"fs.writeFileSync({json.dumps(str(disconnected))},'yes');" + "}")
    preparation = PREPARATION
    if pending == "authentication":
        browser = browser.replace("goto:async()=>{}", "goto:async()=>{" + stuck + "}")
    else:
        preparation = preparation.replace("const r=s.ctx", stuck + "const r=s.ctx")
    profile = tmp_path / "profile"
    proc, outdir, value = start(tmp_path, browser=browser, preparation=preparation, seconds=60,
        env_changes={local_chrome.CHROME_ENV: str(fake_chrome(tmp_path)),
                     local_chrome.PROFILE_ENV: str(profile)})
    try:
        proc.stdin.write(wire(value))
        proc.stdin.flush()
        wait_ready(entered)
        started = time.monotonic()
        output, error = finish(proc)
        assert proc.returncode != 0, error
        assert closed.exists() and disconnected.exists(), "pending setup hid channel abort from cleanup"
        assert time.monotonic() - started < 3, "early failure waited for unrelated work expiry"
        assert output == b""
        assert not (outdir / "effect").exists()
        with pytest.raises(ValueError, match="quarantined"):
            with local_chrome.profile_lease(profile):
                pass
    finally:
        finish(proc)
        clean_pids(profile / "pids")


def test_early_failure_reserves_channel_attempt_after_two_hung_browser_owners(tmp_path):
    import time
    markers = {name: tmp_path / name for name in ("page", "disconnect", "channel")}
    def stuck(name):
        return (f"fs.writeFileSync({json.dumps(str(markers[name]))},String(process.hrtime.bigint()));"
                "await new Promise(()=>{});")
    browser = BROWSER.replace("close:async()=>{}", "close:async()=>{" + stuck("page") + "}")
    browser = browser.replace("disconnect:async()=>{}", "disconnect:async()=>{" + stuck("disconnect") + "}")
    channel_change = lambda text: text.replace("close:() => {", "close:async () => {"
        "const fs=require('node:fs');" + stuck("channel"))
    proc, _, value = start(tmp_path, browser=browser, channel_change=channel_change)
    ready(proc, value)
    started = time.monotonic_ns()
    _, error = finish(proc, b"{}\n")
    assert proc.returncode != 0, error
    assert all(path.exists() for path in markers.values()), "outer owner skipped independent channel close"
    assert int(markers["channel"].read_text()) - started < 10_000_000_000


def test_post_ack_protocol_failure_shares_cleanup_with_stubborn_chrome(tmp_path):
    """Round-3 composed regression: post-ack abort plus sequential nested cleanup."""
    import time
    import local_chrome
    from test_exact_worker import fake_chrome, alive, clean_pids

    profile = tmp_path / "profile"
    chrome = fake_chrome(tmp_path, stubborn=True)
    chrome.write_text(chrome.read_text().replace(
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)",
        "def term(*_):\n"
        "        if not (profile / 'first-term-ns').exists():\n"
        "            (profile / 'first-term-ns').write_text(str(time.monotonic_ns()))\n"
        "    signal.signal(signal.SIGTERM, term)"))
    page_closed, disconnected = tmp_path / "page-closed", tmp_path / "disconnected"
    browser = BROWSER.replace("close:async()=>{}", "close:async()=>{"
        f"fs.writeFileSync({json.dumps(str(page_closed))},String(process.hrtime.bigint()));" + "}")
    browser = browser.replace("disconnect:async()=>{}", "disconnect:async()=>{"
        f"fs.writeFileSync({json.dumps(str(disconnected))},String(process.hrtime.bigint()));" + "}")
    source = SOURCE.replace("for(let sequence=0;", (
        "fs.writeFileSync(s.ctx.outdir+'/node-pid',String(process.pid));"
        "fs.writeFileSync(s.ctx.outdir+'/bad-at',String(process.hrtime.bigint()));"
        "process.stdout.write('{\"unexpected\":true}\\n');"
        "await new Promise(()=>{});for(let sequence=0;"))
    proc, outdir, value = start(tmp_path, source=source, browser=browser, seconds=60,
        env_changes={local_chrome.CHROME_ENV: str(chrome), local_chrome.PROFILE_ENV: str(profile)})
    try:
        ready(proc, value)
        chrome_pid = int((profile / "pids").read_text())
        started = time.monotonic_ns()
        # Observe the existing ~20s defect rather than killing the test at finish()'s 20s guard.
        output, error = proc.communicate(wire(ack(value)), timeout=30)
        ended = time.monotonic_ns()
        bad_at = int((outdir / "bad-at").read_text())
        term_at = int((profile / "first-term-ns").read_text())
        node_pid = int((outdir / "node-pid").read_text())
        try:
            with local_chrome.profile_lease(profile):
                refused = False
        except ValueError as exc:
            refused = "quarantined" in str(exc)
        facts = {
            "exit_code": proc.returncode, "elapsed_after_ack": (ended - started) / 1e9,
            "first_chrome_term_after_failure": (term_at - bad_at) / 1e9,
            "page_cleanup": page_closed.exists(), "disconnect": disconnected.exists(),
            "terminal": b"capture_terminal" in output, "forwarded_bytes": len(output),
            "effect": (outdir / "effect").read_text(),
            "chrome_reaped": not alive(chrome_pid), "node_reaped": not alive(node_pid),
            "lease": (profile / ".linkedin-poster.lease").read_text(),
            "reacquisition_refused": refused,
        }
        (tmp_path / "observations.json").write_text(json.dumps(facts, indent=2))
        (tmp_path / "stderr.log").write_bytes(error)
        assert facts["exit_code"] != 0 and facts["effect"] == "once\n"
        assert not facts["terminal"] and facts["forwarded_bytes"] == 0
        assert facts["chrome_reaped"] and facts["node_reaped"]
        assert facts["reacquisition_refused"] and '"quarantined": true' in facts["lease"]
        failures = []
        if not facts["page_cleanup"] or not facts["disconnect"]:
            failures.append("independent Node cleanup skipped after post-ack failure")
        if facts["first_chrome_term_after_failure"] >= 2:
            failures.append("Chrome TERM delayed behind unnotified Node source")
        if facts["elapsed_after_ack"] >= 14.5:
            failures.append("nested owner restarted cleanup budget beyond 10+2s plus outer settlement")
        assert not failures, (failures, facts)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate(timeout=3)
        clean_pids(profile / "pids")


@pytest.mark.parametrize("owner", ["supervisor", "direct", "node"])
def test_final_control_close_fault_quarantines_actual_stack(tmp_path, monkeypatch, owner):
    from test_exact_worker import fake_chrome, clean_pids
    import local_chrome
    profile = tmp_path / "profile"
    supervisor = SUPERVISOR
    if owner == "direct":
        supervisor = supervisor[:supervisor.index("relay_capture(Path")] + """
from exact_exchange import CaptureExchange
from exact_worker import run_worker
from datetime import datetime, timezone
exchange=CaptureExchange(value,now=datetime.now(timezone.utc))
run_worker(Path(sys.argv[1]),{"capture":value,"outdir":str(sys.argv[2])},
           exchange=exchange,upstream=sys.stdin.buffer.fileno(),downstream=sys.stdout.buffer.fileno())
"""
    if owner in ("supervisor", "direct"):
        supervisor = supervisor.replace("value = decode_capture", """
from capture_control import CleanupContext
real_close=CleanupContext.close
def bad_close(self):
    real_close(self)
    if self.role=='supervisor':raise RuntimeError('final root control close fault')
CleanupContext.close=bad_close
value = decode_capture""")
    monkeypatch.setattr(sys.modules[__name__], "SUPERVISOR", supervisor)
    browser = BROWSER
    if owner == "node":
        browser = browser.replace("disconnect:async()=>{}", """disconnect:async()=>{
const real=fs.closeSync,fd=Number(process.argv[3]);
fs.closeSync=value=>{real(value);if(value===fd)throw Error('final Node control close fault');};
}""")
    proc, outdir, value = start(tmp_path, browser=browser, env_changes={
        local_chrome.CHROME_ENV: str(fake_chrome(tmp_path)), local_chrome.PROFILE_ENV: str(profile)})
    try:
        ready(proc, value)
        _, error = finish(proc, wire(ack(value)))
        assert proc.returncode != 0 and b"control close fault" in error, error
        assert (outdir / "effect").read_text() == "once\n"
        with pytest.raises(ValueError, match="quarantined"):
            with local_chrome.profile_lease(profile):
                pass
    finally:
        finish(proc)
        clean_pids(profile / "pids")


def test_control_fd_inherited_only_by_worker_and_node_not_chrome(tmp_path):
    from test_exact_worker import fake_chrome, clean_pids
    import local_chrome
    profile = tmp_path / "profile"
    chrome = fake_chrome(tmp_path)
    chrome.write_text(chrome.read_text().replace(
        "profile.mkdir(exist_ok=True)",
        "profile.mkdir(exist_ok=True)\n"
        "(profile / 'control-fds').write_text(str(sum('b2-capture-cleanup' in os.readlink("
        "'/proc/self/fd/'+n) for n in os.listdir('/proc/self/fd') "
        "if os.path.exists('/proc/self/fd/'+n))))"))
    source = SOURCE.replace("fs.writeFileSync(s.ctx.outdir+'/source-ready','yes');", """
fs.writeFileSync(s.ctx.outdir+'/node-control-fds',String(fs.readdirSync('/proc/self/fd').filter(n=>{
try{return fs.readlinkSync('/proc/self/fd/'+n).includes('b2-capture-cleanup');}catch{return false;}
}).length));
fs.writeFileSync(s.ctx.outdir+'/source-ready','yes');
""")
    proc, outdir, value = start(tmp_path, source=source, env_changes={
        local_chrome.CHROME_ENV: str(chrome), local_chrome.PROFILE_ENV: str(profile)})
    try:
        ready(proc, value)
        _, error = finish(proc, wire(ack(value)))
        assert proc.returncode == 0, error
        assert (profile / "control-fds").read_text() == "0"
        assert (outdir / "node-control-fds").read_text() == "1"
    finally:
        finish(proc)
        clean_pids(profile / "pids")


def test_channel_detach_failure_still_closes_control(tmp_path):
    marker = tmp_path / "control-closed"
    browser = BROWSER.replace("disconnect:async()=>{}", "disconnect:async()=>{"
        "const close=fs.closeSync,controlFd=Number(process.argv[3]);"
        "fs.closeSync=fd=>{close(fd);if(fd===controlFd)fs.writeFileSync("
        + json.dumps(str(marker)) + ",'yes');};}")
    change = lambda text: text.replace("control, detach, check,", (
        "control, detach:()=>{throw Error('detach cleanup fault');}, check,"))
    proc, outdir, value = start(tmp_path, browser=browser, channel_change=change)
    try:
        ready(proc, value)
        _, error = finish(proc, wire(ack(value)))
        assert proc.returncode != 0, error
        assert marker.exists(), "detach failure skipped independent control close"
        assert (outdir / "effect").read_text() == "once\n"
    finally:
        finish(proc)
