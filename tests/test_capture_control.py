"""Private cleanup cell: real Linux backing and independent process expectations."""
import errno
import os
from pathlib import Path
import struct
import subprocess
import sys
import threading
import time

import pytest

SCRIPTS = Path(__file__).parents[1] / "social/linkedin-post/scripts"
sys.path.insert(0, str(SCRIPTS))


def control():
    from capture_control import CleanupContext, CleanupPolicy
    return CleanupContext.create(time.monotonic_ns() + 60_000_000_000, CleanupPolicy())


def test_failure_first_has_exact_layout_and_single_abort_commit(monkeypatch):
    ctx = control()
    writes = []
    real = os.pwrite
    def write(fd, data, offset):
        writes.append((offset, bytes(data)))
        return real(fd, data, offset)
    monkeypatch.setattr(os, "pwrite", write)
    try:
        ctx.begin(abort=True)
        raw = os.pread(ctx.fd, 128, 0)
        assert raw[:8] == b"B2CLNUP\x01"
        assert struct.unpack_from("<Q", raw, 8)[0] == ctx.expiry
        assert raw[16:32].hex() == ctx.nonce
        assert raw[40] == 2 and raw[41:64] == bytes(23)
        assert raw[64:] == bytes(64)
        assert [(offset, data) for offset, data in writes if offset == 40] == [(40, b"\x02")]
    finally:
        ctx.close()


def test_partial_epoch_is_ignored_then_normal_upgrade_keeps_epoch():
    ctx = control()
    try:
        os.pwrite(ctx.fd, b"\xff" * 7, 64)
        ctx.observe()
        assert ctx.epoch is None and not ctx.aborted
        earlier = time.monotonic_ns() - 1_000_000
        os.pwrite(ctx.fd, struct.pack("<Q", earlier), 64)
        os.pwrite(ctx.fd, b"\x01", 72)
        ctx.observe()
        before = ctx.bounds()
        assert ctx.epoch == earlier and not ctx.aborted
        os.pwrite(ctx.fd, b"\x02", 72)
        ctx.observe()
        assert ctx.aborted and ctx.bounds() == before
    finally:
        ctx.close()


def test_python_publication_serializes_threads_and_reentrant_upgrade(monkeypatch):
    ctx = control()
    real = os.pwrite
    epochs = []
    def write(fd, data, offset):
        if offset == 32:
            epochs.append(bytes(data))
            ctx.begin(abort=True)
        return real(fd, data, offset)
    monkeypatch.setattr(os, "pwrite", write)
    try:
        threads = [threading.Thread(target=ctx.begin) for _ in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)
            assert not thread.is_alive()
        assert len(epochs) == 1 and os.pread(ctx.fd, 1, 40) == b"\x02"
    finally:
        ctx.close()


def test_short_positional_io_and_eintr_complete_before_commit(monkeypatch):
    ctx = control()
    read, write = os.pread, os.pwrite
    calls = [0]
    def short_write(fd, data, offset):
        calls[0] += 1
        if calls[0] == 1:
            raise InterruptedError(errno.EINTR, "fixture")
        return write(fd, data[:1], offset)
    monkeypatch.setattr(os, "pwrite", short_write)
    monkeypatch.setattr(os, "pread", lambda fd, size, offset: read(fd, min(size, 2), offset))
    try:
        ctx.begin(abort=True)
        assert ctx.epoch is not None and ctx.aborted and ctx.error is None
        assert calls[0] == 10
    finally:
        ctx.close()


@pytest.mark.parametrize("mutation", ["state", "reserved", "epoch", "header", "eintr"])
def test_control_failure_freezes_finite_fallback(mutation, monkeypatch):
    ctx = control()
    ctx.begin()
    previous = ctx.bounds()
    if mutation == "state":
        os.pwrite(ctx.fd, b"\x03", 72)
    elif mutation == "reserved":
        os.pwrite(ctx.fd, b"x", 95)
    elif mutation == "epoch":
        os.pwrite(ctx.fd, bytes(8), 32)
    elif mutation == "header":
        os.pwrite(ctx.fd, b"x", 16)
    else:
        def interrupted(*args):
            raise InterruptedError(errno.EINTR, "fixture")
        monkeypatch.setattr(os, "pread", interrupted)
    ctx.observe()
    assert ctx.aborted and ctx.error is not None
    frozen = ctx.bounds()
    assert all(a <= b for a, b in zip(frozen, previous))
    assert ctx.bounds() == frozen
    with pytest.raises(RuntimeError):
        ctx.close()
    assert ctx.fd is None


@pytest.mark.parametrize("wrong", ["nonce", "deadline", "role", "pipe", "lease"])
def test_independent_binding_rejects_before_acquisition(wrong):
    from capture_control import CleanupContext
    ctx = control()
    fd = os.dup(ctx.fd)
    other = None
    expiry, nonce, role, lease = ctx.expiry, ctx.nonce, "worker", -1
    if wrong == "nonce":
        nonce = "00" * 16
    elif wrong == "deadline":
        expiry -= 1
    elif wrong == "role":
        role = "node"
    elif wrong == "pipe":
        os.close(fd)
        fd, other = os.pipe()
    else:
        lease = fd
    try:
        with pytest.raises((ValueError, RuntimeError, OSError)):
            CleanupContext.inherit(fd, expiry, nonce, role, ctx.policy, lease_fd=lease)
        if wrong == "lease":
            os.fstat(fd)  # Rejection must not close a lease alias.
            os.close(fd)
        else:
            with pytest.raises(OSError):
                os.fstat(fd)
    finally:
        if other is not None:
            os.close(other)
        ctx.close()


def test_policy_zero_shorter_and_nested_override():
    from capture_control import CleanupPolicy
    from exact_capture_clock import Deadline
    from process_lifecycle import ProcessScope, CleanupError
    policy = CleanupPolicy.normalize(grace=.1, kill_grace=.5, outer_grace=0)
    assert (policy.term_ns, policy.kill_ns, policy.outer_ns) == (100_000_000, 500_000_000, 0)
    deadline = Deadline(str(time.monotonic_ns() + 60_000_000_000))
    with pytest.raises(CleanupError, match="aborted"), \
            ProcessScope(grace=0, kill_grace=0, capture_deadline=deadline, use_cgroup=False) as root:
        with ProcessScope(grace=0, kill_grace=0, use_cgroup=False) as nested:
            assert nested.capture_context is root.capture_context
        with pytest.raises(ValueError, match="policy"):
            ProcessScope(grace=.1, use_cgroup=False)
        t, k = root.begin_cleanup()
        assert t == k


def test_control_close_failure_retains_unknown_and_does_not_retry(monkeypatch):
    ctx = control()
    real = os.close
    calls = []
    def close(fd):
        calls.append(fd)
        real(fd)
        raise InterruptedError(errno.EINTR, "ambiguous close")
    monkeypatch.setattr(os, "close", close)
    with pytest.raises(RuntimeError):
        ctx.close()
    ctx.close()
    assert len(calls) == 1 and ctx.fd is None


def node_control(ctx, script):
    args = ctx.arguments("node")
    source = "const {openControl}=require('./capture_control');" + script
    return subprocess.Popen(["node", "-e", source, args[0], str(ctx.expiry), *args[1:]],
        cwd=SCRIPTS, pass_fds=(ctx.fd,), stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def test_node_cleanup_active_wait_tightens_on_earlier_normal_epoch():
    import json
    ctx = control()
    proc = node_control(ctx, """
const c=openControl(process.argv.slice(1));
c.startCleanup();console.log('ready');
c.settle(()=>new Promise(()=>{}),{phase:'channel'}).then(
 ()=>{throw Error('unexpected resolution');},
 ()=>{console.log(JSON.stringify({abort:c.aborted,epoch:String(c.epoch)}));c.close();});
""")
    try:
        assert proc.stdout.readline() == b"ready\n", proc.stderr.read()
        started = time.monotonic()
        earlier = time.monotonic_ns() - 9_800_000_000
        os.pwrite(ctx.fd, struct.pack("<Q", earlier), 64)
        os.pwrite(ctx.fd, b"\x01", 72)
        output, error = proc.communicate(timeout=2)
        assert proc.returncode == 0, error
        assert time.monotonic() - started < 1
        assert json.loads(output) == {"abort": False, "epoch": str(earlier)}
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()
        ctx.close()


def test_node_observes_abort_after_ack_stream_is_absent():
    ctx = control()
    proc = node_control(ctx, """
const c=openControl(process.argv.slice(1));console.log('ready');
c.settle(()=>new Promise(()=>{})).catch(e=>{
 console.log(c.aborted?'aborted':'wrong');c.startCleanup();c.close();});
""")
    try:
        assert proc.stdout.readline() == b"ready\n", proc.stderr.read()
        ctx.begin(abort=True)
        output, error = proc.communicate(timeout=2)
        assert proc.returncode == 0 and output == b"aborted\n", error
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()
        ctx.close()


@pytest.mark.parametrize("committed", [False, True])
def test_process_exit_retains_only_committed_epoch(committed):
    ctx = control()
    source = """
import os,struct,sys,time
fd=int(sys.argv[1])
os.pwrite(fd,struct.pack('<Q',time.monotonic_ns()),64)
if sys.argv[2]=='True':os.pwrite(fd,b'\\x02',72)
os._exit(7)
"""
    try:
        proc = subprocess.run([sys.executable, "-c", source, str(ctx.fd), str(committed)],
                              pass_fds=(ctx.fd,), timeout=2)
        assert proc.returncode == 7
        ctx.observe()
        assert (ctx.epoch is not None) is committed
        assert ctx.aborted is committed
    finally:
        ctx.close()


def test_root_control_close_failure_quarantines_profile_after_nested_return(tmp_path, monkeypatch):
    from exact_capture_clock import Deadline
    from process_lifecycle import ProcessScope, CleanupError
    from profile_lease import ProfileLease
    deadline = Deadline(str(time.monotonic_ns() + 60_000_000_000))
    profile = tmp_path / "profile"
    with pytest.raises(CleanupError, match="control close"):
        with ProcessScope(capture_deadline=deadline, use_cgroup=False) as root:
            close = root.capture_context.close
            def broken_close():
                close()
                raise RuntimeError("control close unknown")
            monkeypatch.setattr(root.capture_context, "close", broken_close)
            with ProfileLease(profile):
                with ProcessScope(use_cgroup=False):
                    pass
    with pytest.raises(ValueError, match="quarantined"):
        with ProfileLease(profile):
            pass


@pytest.mark.parametrize("borrowed", [False, True])
@pytest.mark.parametrize("interrupt", [False, True])
def test_root_lease_held_through_control_close_and_interrupt(tmp_path, monkeypatch, borrowed, interrupt):
    import contextlib
    import signal
    import profile_lease as leases
    from exact_capture_clock import Deadline
    from process_lifecycle import ProcessScope, CleanupError, cleanup_failure
    profile = tmp_path / "profile"
    deadline = Deadline(str(time.monotonic_ns() + 60_000_000_000))
    outside = leases.ProfileLease(profile) if borrowed else contextlib.nullcontext()
    seen = []
    with pytest.raises(SystemExit if interrupt else CleanupError) as caught:
        with outside as held:
            if borrowed:
                monkeypatch.setattr(leases, "_inherited", (profile.resolve(), held.fd))
            with ProcessScope(capture_deadline=deadline, use_cgroup=False) as root:
                close = root.capture_context.close
                def close_fault():
                    # Same inode and lock remain held after nested lexical release.
                    assert lease.fd is not None
                    assert (profile / leases.LEASE_NAME).read_bytes() == leases.ACTIVE
                    seen.append(lease.fd)
                    close()
                    if interrupt:
                        os.kill(os.getpid(), signal.SIGTERM)
                    raise RuntimeError("final control close fault")
                monkeypatch.setattr(root.capture_context, "close", close_fault)
                with leases.ProfileLease(profile) as lease:
                    with ProcessScope(use_cgroup=False):
                        pass
    assert len(seen) == 1 and lease.fd is None
    if interrupt:
        assert caught.value.code == 143
        assert "final control close fault" in str(cleanup_failure(caught.value))
    monkeypatch.setattr(leases, "_inherited", None)
    with pytest.raises(ValueError, match="quarantined"):
        with leases.ProfileLease(profile):
            pass


def test_healthy_lease_releases_only_after_single_root_control_close(tmp_path, monkeypatch):
    from exact_capture_clock import Deadline
    from process_lifecycle import ProcessScope
    from profile_lease import ProfileLease, LEASE_NAME, ACTIVE
    profile = tmp_path / "profile"
    calls = []
    with ProcessScope(capture_deadline=Deadline(str(time.monotonic_ns()+60_000_000_000)),
                      use_cgroup=False) as root:
        close = root.capture_context.close
        def record():
            assert lease.fd is not None and (profile / LEASE_NAME).read_bytes() == ACTIVE
            calls.append("close")
            close()
        monkeypatch.setattr(root.capture_context, "close", record)
        with ProfileLease(profile) as lease:
            for _ in range(2):
                with ProcessScope(use_cgroup=False):
                    pass
        assert calls == [] and lease.fd is not None
    assert calls == ["close"] and lease.fd is None
    with ProfileLease(profile):
        pass


def test_late_root_failure_reaches_retained_lease(tmp_path):
    from exact_capture_clock import Deadline
    from process_lifecycle import ProcessScope, cleanup_failure
    from profile_lease import ProfileLease
    profile = tmp_path / "profile"
    original = ValueError("snapshot cleanup failed")
    with pytest.raises(ValueError) as caught:
        with ProcessScope(capture_deadline=Deadline(str(time.monotonic_ns()+60_000_000_000)),
                          use_cgroup=False):
            with ProfileLease(profile):
                pass
            raise original
    assert caught.value is original
    assert cleanup_failure(caught.value) is not None
    with pytest.raises(ValueError, match="quarantined"):
        with ProfileLease(profile):
            pass


def test_auxiliary_probe_policy_and_fd_exemption_then_failure():
    from exact_capture_clock import Deadline
    from process_lifecycle import ProcessScope, CleanupError
    from process_output import run_bounded
    code = ("import os; print(any('b2-capture-cleanup' in os.readlink('/proc/self/fd/'+n) "
            "for n in os.listdir('/proc/self/fd') if os.path.exists('/proc/self/fd/'+n)))")
    with pytest.raises(CleanupError, match="aborted"), \
            ProcessScope(capture_deadline=Deadline(str(time.monotonic_ns()+60_000_000_000)),
                         use_cgroup=False, grace=.6) as root:
        result = run_bounded([sys.executable, "-c", code], input="", timeout=2, grace=.01,
                             capture_deadline=root.capture_deadline, auxiliary=True)
        assert result.stdout == "False\n"
        assert root.capture_context.epoch is None
        assert root.capture_context.policy.term_ns == 600_000_000
        run_bounded([sys.executable, "-c", "raise SystemExit(3)"], input="", timeout=2,
                    capture_deadline=root.capture_deadline, auxiliary=True)
        assert root.capture_context.epoch is not None and root.capture_context.aborted


def test_auxiliary_release_failure_activates_even_when_caller_catches(monkeypatch):
    from exact_capture_clock import Deadline
    from process_lifecycle import ProcessScope, CleanupError
    with pytest.raises(CleanupError, match="aborted"), \
            ProcessScope(capture_deadline=Deadline(str(time.monotonic_ns()+60_000_000_000)),
                         use_cgroup=False) as root:
        with pytest.raises(CleanupError):
            with ProcessScope(use_cgroup=False, auxiliary=True) as probe:
                close = probe.root.close
                def fail_close():
                    close()
                    raise RuntimeError("probe handle release unknown")
                monkeypatch.setattr(probe.root, "close", fail_close)
        assert root.capture_context.epoch is not None and root.capture_context.aborted


def test_partial_epoch_write_failure_never_commits(monkeypatch):
    ctx = control()
    write = os.pwrite
    def broken(fd, data, offset):
        if offset == 32:
            return write(fd, data[:3], offset)
        raise OSError("epoch write failed")
    monkeypatch.setattr(os, "pwrite", broken)
    ctx.begin(abort=True)
    assert ctx.error is not None and os.pread(ctx.fd, 1, 40) == b"\0"
    with pytest.raises(RuntimeError):
        ctx.close()


def test_normal_abort_upgrade_between_state_reads_is_valid(monkeypatch):
    ctx = control()
    epoch = time.monotonic_ns()
    os.pwrite(ctx.fd, struct.pack("<Q", epoch), 64)
    os.pwrite(ctx.fd, b"\x01", 72)
    read = os.pread
    def race(fd, length, offset):
        data = read(fd, length, offset)
        if offset == 72 and data == b"\x01":
            os.pwrite(fd, b"\x02", 72)
        return data
    monkeypatch.setattr(os, "pread", race)
    try:
        ctx.observe()
        assert ctx.error is None and ctx.aborted and ctx.epoch == epoch
    finally:
        ctx.close()


@pytest.mark.parametrize("bad", ["policy", "missing", "deadline"])
def test_partial_bootstrap_closes_owned_copy(bad):
    from capture_control import CleanupContext
    ctx = control()
    fields = ctx.arguments("worker")
    fd = os.dup(ctx.fd)
    fields[0] = str(fd)
    expiry = str(ctx.expiry)
    if bad == "policy":
        fields[-1] = "2000000001"
    elif bad == "missing":
        fields.pop()
    else:
        expiry = "01"
    try:
        with pytest.raises(ValueError):
            CleanupContext.from_arguments(expiry, fields)
        with pytest.raises(OSError):
            os.fstat(fd)
        os.fstat(ctx.fd)
    finally:
        ctx.close()


def test_node_close_fault_nonzero_without_leaking_referenced_guard():
    ctx = control()
    proc = node_control(ctx, """
const c=openControl(process.argv.slice(1)),fs=require('node:fs'),close=fs.closeSync;
fs.closeSync=fd=>{close(fd);throw Object.assign(Error('close unknown'),{code:'EINTR'});};
try {c.close();process.exitCode=0;}catch(e){console.error(e.message);process.exitCode=7;}
""")
    try:
        _, error = proc.communicate(timeout=2)
        assert proc.returncode == 7 and b"close unknown" in error
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()
        ctx.close()


@pytest.mark.parametrize("term", [0, .1, .6])
def test_node_short_policy_slices_and_zero_never_enter_pending_work(term):
    import json
    from capture_control import CleanupContext, CleanupPolicy
    ctx = CleanupContext.create(time.monotonic_ns()+60_000_000_000,
                                CleanupPolicy.normalize(grace=term, kill_grace=0))
    proc = node_control(ctx, """
const c=openControl(process.argv.slice(1));c.startCleanup();
const interval=c.limits[0]-c.cleanupEntry, reserve=c.limits[0]-c.browserEnd();
let entered=false;
c.settle(()=>{entered=true;return new Promise(()=>{});},{phase:'browser',share:2}).catch(()=>{
 console.log(JSON.stringify({entered,interval:String(interval),reserve:String(reserve)}));c.close();});
""")
    try:
        output, error = proc.communicate(timeout=2)
        assert proc.returncode == 0, error
        facts = json.loads(output)
        assert facts["entered"] is (term > 0)
        assert 0 <= int(facts["reserve"]) <= max(0, int(facts["interval"]))
        assert int(facts["interval"]) <= int(term * 1e9)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()
        ctx.close()


def test_python_active_reap_wait_tightens_on_normal_earlier_epoch(tmp_path):
    from exact_capture_clock import Deadline
    from process_lifecycle import ProcessScope, CleanupError
    expiry = time.monotonic_ns()+60_000_000_000
    started = time.monotonic()
    ready = tmp_path / "ready"
    proc = None
    with pytest.raises(CleanupError, match="forced escalation"):
        with ProcessScope(capture_deadline=Deadline(str(expiry)), use_cgroup=False) as root:
            proc = root.spawn([sys.executable, "-c",
                "import pathlib,signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);"
                f"pathlib.Path({str(ready)!r}).write_text('yes');time.sleep(60)"])
            from test_process_lifecycle import wait_ready
            wait_ready(ready)
            def earlier():
                time.sleep(.1)
                os.pwrite(root.capture_context.fd, struct.pack("<Q", time.monotonic_ns()-11_000_000_000), 64)
                os.pwrite(root.capture_context.fd, b"\x01", 72)
            publisher = threading.Thread(target=earlier)
            publisher.start()
    publisher.join(timeout=2)
    assert proc.returncode == -9
    assert time.monotonic()-started < 2


def test_partial_root_entry_closes_control_and_restores_signals(monkeypatch):
    import signal
    from exact_capture_clock import Deadline
    from process_lifecycle import ProcessScope, OwnedCgroup
    before = set(os.listdir("/proc/self/fd"))
    handlers = [signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)]
    def fail(*args):
        raise RuntimeError("cgroup creation fault")
    monkeypatch.setattr(OwnedCgroup, "create", fail)
    with pytest.raises(RuntimeError, match="creation fault"):
        with ProcessScope(capture_deadline=Deadline(str(time.monotonic_ns()+60_000_000_000))):
            pass
    assert set(os.listdir("/proc/self/fd")) == before
    assert handlers == [signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)]


def test_caught_nested_failure_cannot_make_root_attest_clean(tmp_path):
    from exact_capture_clock import Deadline
    from process_lifecycle import ProcessScope, CleanupError
    from profile_lease import ProfileLease
    profile = tmp_path / "profile"
    with pytest.raises(CleanupError, match="nested fault"):
        with ProcessScope(capture_deadline=Deadline(str(time.monotonic_ns()+60_000_000_000)),
                          use_cgroup=False):
            try:
                with ProfileLease(profile):
                    raise ValueError("nested fault")
            except ValueError:
                pass
    with pytest.raises(ValueError, match="quarantined"):
        with ProfileLease(profile):
            pass


def test_peer_abort_at_final_observation_prevents_root_success():
    from exact_capture_clock import Deadline
    from process_lifecycle import ProcessScope, CleanupError
    with pytest.raises(CleanupError, match="aborted"):
        with ProcessScope(capture_deadline=Deadline(str(time.monotonic_ns()+60_000_000_000)),
                          use_cgroup=False) as root:
            epoch = time.monotonic_ns()
            os.pwrite(root.capture_context.fd, struct.pack("<Q", epoch), 64)
            os.pwrite(root.capture_context.fd, b"\x02", 72)
