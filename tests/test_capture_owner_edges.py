"""Runtime SPEC edge regressions: real owners, offline processes, injected I/O faults."""
import errno
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import sys
import time

import pytest

from test_capture_control import control, node_control, SCRIPTS
import test_capture_relay_stack as stack
from test_capture_exchange import wire, ack
from test_exact_worker import fake_chrome, clean_pids
from test_process_lifecycle import wait_ready


@pytest.mark.parametrize("fault", ["epoch", "commit", "observe"])
def test_local_receipt_survives_first_publication_failure(monkeypatch, fault):
    import capture_control as cc
    ctx = control()
    now = time.monotonic_ns()
    receipt = now - 9_000_000_000
    monkeypatch.setattr(cc, "now_ns", lambda: now)
    write, read = os.pwrite, os.pread
    def broken_write(fd, data, offset):
        if offset == (32 if fault == "epoch" else 40):
            raise OSError(errno.EIO, "publication fault")
        return write(fd, data, offset)
    def broken_read(fd, size, offset):
        if offset == 0:
            raise OSError(errno.EIO, "observation fault")
        return read(fd, size, offset)
    monkeypatch.setattr(os, "pread" if fault == "observe" else "pwrite",
                        broken_read if fault == "observe" else broken_write)
    try:
        ctx.begin(abort=True, at=receipt)
        assert ctx.error is not None
        assert read(ctx.fd, 1, 40) == b"\0"
        assert ctx.epoch == receipt
        assert ctx.bounds() == (receipt + 10_000_000_000, receipt + 12_000_000_000,
                                receipt + 14_000_000_000)
        monkeypatch.setattr(cc, "now_ns", lambda: now + 5_000_000_000)
        assert ctx.bounds()[0] == receipt + 10_000_000_000
    finally:
        with pytest.raises(RuntimeError):
            ctx.close()


@pytest.mark.parametrize("fault", [False, True])
def test_reentrant_earlier_receipt_tightens_local_origin(monkeypatch, fault):
    ctx = control()
    receipt = time.monotonic_ns() - 9_000_000_000
    write = os.pwrite
    entered = False
    def reenter(fd, data, offset):
        nonlocal entered
        if offset == 32 and not entered:
            entered = True
            ctx.begin(abort=True, at=receipt)
            if fault:
                raise OSError(errno.EIO, "outer publication failed")
        return write(fd, data, offset)
    monkeypatch.setattr(os, "pwrite", reenter)
    try:
        ctx.begin()
        assert ctx.epoch == receipt
        assert ctx.bounds()[0] == receipt + 10_000_000_000
        assert ctx.aborted
        assert os.pread(ctx.fd, 1, 40) == (b"\0" if fault else b"\2")
    finally:
        if fault:
            with pytest.raises(RuntimeError):
                ctx.close()
        else:
            ctx.close()


@pytest.mark.parametrize("at", [-1, 0, True, "1", "future"])
def test_invalid_local_receipt_cannot_publish(monkeypatch, at):
    ctx = control()
    if at == "future":
        at = time.monotonic_ns() + 1_000_000_000
    try:
        with pytest.raises(ValueError, match="epoch"):
            ctx.begin(at=at)
        assert os.pread(ctx.fd, 32, 32) == bytes(32)
        assert ctx.epoch is None
    finally:
        ctx.close()


@pytest.mark.parametrize("fault", ["epoch", "commit", "observe"])
def test_node_publication_failure_keeps_entry_origin(fault):
    ctx = control()
    proc = node_control(ctx, """
const c=openControl(process.argv.slice(1)),fs=require('node:fs');
const entry=process.hrtime.bigint(),write=fs.writeSync,read=fs.readSync;
let clock=entry;process.hrtime.bigint=()=>clock;
const fault=FAULT;
fs.writeSync=(fd,b,o,n,p)=>{
 if(fd===c.fd && p===(fault==='epoch'?96:104)){
   clock=entry+9000000000n;throw Error('publication fault');
 }return write(fd,b,o,n,p);
};
fs.readSync=(fd,b,o,n,p)=>{
 if(fault==='observe' && fd===c.fd && p===0){
   clock=entry+9000000000n;throw Error('observation fault');
 }return read(fd,b,o,n,p);
};
c.begin(true);
const state=Buffer.alloc(1);read(c.fd,state,0,1,104);
console.log(JSON.stringify({entry:String(entry),epoch:String(c.epoch),
 t:String(c.limits[0]),state:state[0],error:!!c.error}));
try{c.close();}catch{}
""".replace("FAULT", json.dumps(fault)))
    try:
        output, error = proc.communicate(timeout=3)
        assert proc.returncode == 0, error
        facts = json.loads(output)
        assert facts["error"] and facts["state"] == 0
        assert facts["epoch"] == facts["entry"]
        assert int(facts["t"]) == int(facts["entry"]) + 10_000_000_000
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()
        ctx.close()


def test_normal_publication_keeps_earlier_local_origin_without_mutating_committed_slot():
    ctx = control()
    try:
        ctx.begin()
        published = os.pread(ctx.fd, 8, 32)
        receipt = ctx.epoch - 9_000_000_000
        ctx.begin(at=receipt)
        assert ctx.bounds()[0] == receipt + 10_000_000_000
        assert not ctx.aborted and os.pread(ctx.fd, 1, 40) == b"\1"
        assert os.pread(ctx.fd, 8, 32) == published
    finally:
        ctx.close()


def test_node_reentrant_abort_cannot_downgrade_commit_or_restart_local_budget():
    ctx = control()
    proc = node_control(ctx, """
const c=openControl(process.argv.slice(1)),fs=require('node:fs'),write=fs.writeSync;
const entry=process.hrtime.bigint();let clock=entry,entered=false;
process.hrtime.bigint=()=>clock;
fs.writeSync=(fd,b,o,n,p)=>{
 if(fd===c.fd && p===96 && !entered){
  entered=true;clock=entry+9000000000n;c.begin(true);
 }return write(fd,b,o,n,p);
};
c.begin();
console.log(JSON.stringify({entry:String(entry),epoch:String(c.epoch),
 t:String(c.limits[0]),state:fs.readFileSync('/proc/self/fd/'+c.fd)[104],aborted:c.aborted}));
c.close();
""")
    try:
        output, error = proc.communicate(timeout=3)
        assert proc.returncode == 0, error
        facts = json.loads(output)
        assert facts["state"] == 2 and facts["aborted"]
        assert facts["epoch"] == facts["entry"]
        assert int(facts["t"]) == int(facts["entry"]) + 10_000_000_000
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()
        ctx.close()


def display_fixture(tmp_path, *, delayed=False):
    path = tmp_path / "fake-xvfb"
    path.write_text(f"""#!{sys.executable}
import os,pathlib,signal,sys,time
p=pathlib.Path({str(tmp_path)!r})
def term(*_):
    (p/'term-ns').write_text(str(time.monotonic_ns()))
    raise SystemExit(0)
signal.signal(signal.SIGTERM,term)
(p/'display-pid').write_text(str(os.getpid()))
(p/'display-ready').write_text('yes')
if {delayed!r}:
    time.sleep(.16)
    os.write(int(sys.argv[sys.argv.index('-displayfd')+1]),b'91\\n')
while True:time.sleep(.05)
""")
    path.chmod(0o755)
    return path


@pytest.mark.parametrize("owner", ["display", "endpoint"])
def test_capture_startup_wait_slices_stay_within_fifty_ms(tmp_path, monkeypatch, owner):
    import local_chrome as lc
    from exact_capture_clock import Deadline
    from process_lifecycle import ProcessScope
    waits = []
    select, sleep = lc.select.select, time.sleep
    def selected(read, write, error, timeout):
        if timeout:
            waits.append(timeout)
        return select(read, write, error, timeout)
    def slept(seconds):
        waits.append(seconds)
        return sleep(seconds)
    monkeypatch.setattr(lc.select, "select", selected)
    monkeypatch.setattr(time, "sleep", slept)
    monkeypatch.setenv(lc.XVFB_ENV, str(display_fixture(tmp_path, delayed=True)))
    with ProcessScope(grace=.6, use_cgroup=False,
                      capture_deadline=Deadline(str(time.monotonic_ns()+60_000_000_000))) as root:
        if owner == "display":
            with lc._run_display() as display:
                assert display == {"DISPLAY": ":91"}
        else:
            profile = tmp_path / "profile"
            executable = fake_chrome(tmp_path)
            executable.write_text(executable.read_text().replace(
                "(profile / 'DevToolsActivePort').write_text", "time.sleep(.16)\n    (profile / 'DevToolsActivePort').write_text"))
            child = root.spawn([str(executable), "--user-data-dir=" + str(profile)])
            assert lc._endpoint(profile, child) == "ws://127.0.0.1:1234/devtools/browser/fake"
    assert len(waits) >= 3 and all(0 < wait <= .05 for wait in waits)


@pytest.mark.parametrize("owner", ["display", "endpoint"])
def test_stack_startup_abort_observed_before_outer_fallback(tmp_path, owner):
    import local_chrome as lc
    profile = tmp_path / "profile"
    chrome = fake_chrome(tmp_path, startup=owner == "display")
    env = {lc.CHROME_ENV: str(chrome), lc.PROFILE_ENV: str(profile)}
    marker = tmp_path / "term-ns"
    if owner == "display":
        env[lc.XVFB_ENV] = str(display_fixture(tmp_path))
        started = tmp_path / "display-ready"
        pids = tmp_path / "display-pid"
    else:
        chrome.write_text(chrome.read_text().replace("while True:",
            f"def term(*_):\n    pathlib.Path({str(marker)!r}).write_text(str(time.monotonic_ns()))\n"
            "    raise SystemExit(0)\nsignal.signal(signal.SIGTERM,term)\nwhile True:"))
        started = pids = profile / "pids"
    proc, outdir, value = stack.start(tmp_path, env_changes=env)
    try:
        proc.stdin.write(wire(value))
        proc.stdin.flush()
        wait_ready(started)
        at = time.monotonic_ns()
        output, error = stack.finish(proc)
        elapsed = (time.monotonic_ns() - at) / 1e9
        facts = {"exit": proc.returncode, "elapsed": elapsed, "term": marker.exists(),
                 "first_term_after_eof": (int(marker.read_text()) - at) / 1e9 if marker.exists() else None,
                 "stdout_bytes": len(output), "effect": (outdir / "effect").exists(),
                 "reaped": not Path("/proc/" + pids.read_text().strip()).exists(),
                 "lease": (profile / ".linkedin-poster.lease").read_text()}
        (tmp_path / "observations.json").write_text(json.dumps(facts, indent=2))
        assert proc.returncode != 0, error
        assert facts["term"] and elapsed < 2
        assert facts["reaped"] and not facts["effect"] and output == b""
        with pytest.raises(ValueError, match="quarantined"):
            with lc.profile_lease(profile):
                pass
        facts["reacquisition_refused"] = True
        (tmp_path / "observations.json").write_text(json.dumps(facts, indent=2))
    finally:
        stack.finish(proc)
        clean_pids(pids)


@pytest.mark.parametrize("owner", ["display", "endpoint"])
def test_real_sigterm_during_startup_reaps_before_owner_returns(tmp_path, owner):
    display = display_fixture(tmp_path)
    script = """
import json,os,pathlib,sys,time
import local_chrome as lc
from exact_capture_clock import Deadline
from process_lifecycle import ProcessScope,cleanup_failure
from profile_lease import ProfileLease
p=pathlib.Path(sys.argv[1]);lc.STARTUP_S=2
os.environ[lc.XVFB_ENV]=str(p/'fake-xvfb')
root=ProcessScope(grace=.1,kill_grace=.1,use_cgroup=False,
 capture_deadline=Deadline(str(time.monotonic_ns()+60000000000)))
try:
 with root,ProfileLease(p/'profile'):
  if sys.argv[2]=='display':
   with lc._run_display():raise AssertionError('unexpected startup')
  else:
   child=root.spawn([str(p/'fake-xvfb')])
   lc._endpoint(p/'profile',child)
except SystemExit as e:
 facts={'code':e.code,'returned':time.monotonic_ns(),
        'reaped':[x.returncode for x in root.processes],
        'typed':str(cleanup_failure(e))}
 (p/'result.json').write_text(json.dumps(facts))
"""
    env = {**os.environ, "PYTHONPATH": str(SCRIPTS)}
    proc = subprocess.Popen([sys.executable, "-c", script, str(tmp_path), owner],
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        wait_ready(tmp_path / "display-ready")
        at = time.monotonic_ns()
        proc.send_signal(signal.SIGTERM)
        output, error = proc.communicate(timeout=5)
        assert proc.returncode == 0, (output, error)
        facts = json.loads((tmp_path / "result.json").read_text())
        facts["elapsed_after_signal"] = (facts["returned"] - at) / 1e9
        term = tmp_path / "term-ns"
        facts["first_term_after_signal"] = (int(term.read_text()) - at) / 1e9 if term.exists() else None
        (tmp_path / "observations.json").write_text(json.dumps(facts, indent=2))
        assert facts["code"] == 143
        assert facts["elapsed_after_signal"] < .5
        assert facts["reaped"] == [0]
        assert (tmp_path / "term-ns").exists()
        assert not Path("/proc/" + (tmp_path / "display-pid").read_text()).exists()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()
        clean_pids(tmp_path / "display-pid")


DIRECT = stack.SUPERVISOR[:stack.SUPERVISOR.index("relay_capture(Path")] + """
from exact_exchange import CaptureExchange
from exact_worker import run_worker
from datetime import datetime,timezone
exchange=CaptureExchange(value,now=datetime.now(timezone.utc))
run_worker(Path(sys.argv[1]),{'capture':value,'outdir':str(sys.argv[2])},grace=.6,
 exchange=exchange,upstream=sys.stdin.buffer.fileno(),downstream=sys.stdout.buffer.fileno())
"""


def test_short_policy_stack_accepts_delayed_display_and_clean_capture(tmp_path, monkeypatch):
    import local_chrome as lc
    bounds_check = """
from capture_control import CleanupContext
real_close=CleanupContext.close
def checked_close(self):
 if self.role=='supervisor':
  t,k,o=self.bounds()
  assert self.policy.term_ns==600000000
  assert t==min(self.epoch+600000000,self.expiry-5000000000)
  assert k==min(t+2000000000,self.expiry-3000000000)
  assert o==min(k+2000000000,self.expiry)
  import json
  Path(sys.argv[2]+'/bounds.json').write_text(json.dumps(
   {'epoch':self.epoch,'bounds':[t,k,o],'policy':self.policy.values()}))
 return real_close(self)
CleanupContext.close=checked_close
"""
    monkeypatch.setattr(stack, "SUPERVISOR", DIRECT.replace("value = decode_capture", bounds_check + "\nvalue = decode_capture"))
    profile = tmp_path / "profile"
    source = stack.SOURCE.replace("fs.writeFileSync(s.ctx.outdir+'/source-ready','yes');",
        "if(process.argv[7]!=='600000000')throw Error('root policy not inherited');"
        "fs.writeFileSync(s.ctx.outdir+'/policy',JSON.stringify(process.argv.slice(7,10)));"
        "fs.writeFileSync(s.ctx.outdir+'/source-ready','yes');")
    proc, outdir, value = stack.start(tmp_path, source=source, env_changes={
        lc.CHROME_ENV: str(fake_chrome(tmp_path)), lc.PROFILE_ENV: str(profile),
        lc.XVFB_ENV: str(display_fixture(tmp_path, delayed=True))})
    try:
        stack.ready(proc, value)
        output, error = stack.finish(proc, wire(ack(value)))
        assert proc.returncode == 0, error
        assert b"capture_terminal" in output
        assert (outdir / "effect").read_text() == "once\n"
        assert json.loads((outdir / "policy").read_text()) == ["600000000", "2000000000", "2000000000"]
        bounds = json.loads((outdir / "bounds.json").read_text())
        assert bounds["bounds"][0] - bounds["epoch"] == 600_000_000
        assert (tmp_path / "term-ns").exists()
        assert (profile / ".linkedin-poster.lease").read_bytes() == b""
    finally:
        stack.finish(proc)
        clean_pids(profile / "pids")
        clean_pids(tmp_path / "display-pid")


def test_stack_empty_lease_fsync_failure_quarantines_before_unlock(tmp_path, monkeypatch):
    import local_chrome as lc
    inject = """
import errno,os
real_fsync=os.fsync
def failed_empty_fsync(fd):
 if os.readlink('/proc/self/fd/'+str(fd)).endswith('/.linkedin-poster.lease') and os.fstat(fd).st_size==0:
  raise OSError(errno.EIO,'empty lease fsync fault')
 return real_fsync(fd)
os.fsync=failed_empty_fsync
"""
    monkeypatch.setattr(stack, "SUPERVISOR", stack.SUPERVISOR.replace("value = decode_capture", inject + "\nvalue = decode_capture"))
    profile = tmp_path / "profile"
    proc, outdir, value = stack.start(tmp_path, env_changes={
        lc.CHROME_ENV: str(fake_chrome(tmp_path)), lc.PROFILE_ENV: str(profile)})
    try:
        stack.ready(proc, value)
        output, error = stack.finish(proc, wire(ack(value)))
        marker = (profile / ".linkedin-poster.lease").read_text()
        facts = {"exit": proc.returncode, "terminal": b"capture_terminal" in output,
                 "effect": (outdir / "effect").read_text(), "lease": marker}
        (tmp_path / "observations.json").write_text(json.dumps(facts, indent=2))
        assert proc.returncode != 0 and b"empty lease fsync fault" in error
        assert facts["terminal"] and facts["effect"] == "once\n"
        assert '"quarantined": true' in marker
        with pytest.raises(ValueError, match="quarantined"):
            with lc.profile_lease(profile):
                pass
        facts["reacquisition_refused"] = True
        (tmp_path / "observations.json").write_text(json.dumps(facts, indent=2))
    finally:
        stack.finish(proc)
        clean_pids(profile / "pids")
