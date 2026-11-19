"""Actual pipes, inclusive budgets and the capture-only incremental framing mode."""
import json
import time
import sys

import pytest

from test_exact_relay import ACK, READY, DRIVER, LAUNCHER, SCRIPTS, finish, launch

sys.path.insert(0, str(SCRIPTS))

CAPTURE_LAUNCHER = LAUNCHER.replace(
    "from process_output import run_stream",
    "from process_output import run_stream\nfrom exact_capture_clock import Deadline\nimport time"
).replace(
    'if value == {"disposition":"uncertain"}:',
    'if value.get("kind") in ("chunk", "declaration"): return value["kind"]\n'
    '    if value == {"disposition":"uncertain"}:'
).replace(
    'timeout=float(sys.argv[3]), grace=.1)',
    'timeout=float(sys.argv[3]), grace=.1, capture_deadline=Deadline('
    'str(time.monotonic_ns() + int((float(sys.argv[3]) + 15) * 1e9))))'
)
STREAM = DRIVER.replace(
    """print('{"disposition":"uncertain"}', flush=True)""",
    """import os
parts = [json.dumps({"kind":"chunk","payload":"x"*43692}).encode()+b'\\n' for _ in range(32)]
parts += [b'{"kind":"declaration"}\\n', b'{"disposition":"uncertain"}\\n']
os.write(1, b''.join(parts))
""")


def test_capture_coalesced_full_stream_exceeds_legacy_budget(tmp_path):
    proc, marker = launch(tmp_path, STREAM, launcher=CAPTURE_LAUNCHER)
    assert proc.stdout.readline() == READY
    output, error = finish(proc, ACK)
    assert proc.returncode == 0, error
    assert len(output.splitlines()) == 34
    assert len(output) > 1024 * 1024
    assert marker.read_text() == "effect"


@pytest.mark.parametrize("grace,clean", [(.6, True), (.1, False)])
def test_capture_fragmented_stream_and_terminal_cleanup_observation(tmp_path, grace, clean):
    driver = DRIVER.replace(
        """print('{"disposition":"uncertain"}', flush=True)""",
        """import os,time
for byte in b'{"kind":"declaration"}\\n{"disposition":"uncertain"}\\n':
    os.write(1, bytes([byte]))
# Work cutoff stops production, not post-terminal EOF/exit observation.
time.sleep(.4)
""")
    # Shared normal cleanup now obeys the root policy too. A .4s release needs
    # a .6s root allowance; .1s must expire rather than silently grant another wait.
    launcher = CAPTURE_LAUNCHER.replace("grace=.1", f"grace={grace}")
    proc, _ = launch(tmp_path, driver, timeout=.3, launcher=launcher)
    assert proc.stdout.readline() == READY
    output, error = finish(proc, ACK)
    assert (proc.returncode == 0) is clean, error
    assert len(output.splitlines()) == 2


@pytest.mark.parametrize("bad", [
    b'{"kind":"chunk"}\r\n',
    b'{"kind":"chunk","padding":"' + b"x" * 65536 + b'"}\n',
    b'{"kind":"chunk"}\n' * 33 + b'{"kind":"declaration"}\n{"disposition":"uncertain"}\n',
    b'{"kind":"declaration"}\n{"kind":"chunk"}\n',
])
def test_capture_frame_order_and_limits(tmp_path, bad):
    driver = DRIVER.replace("""print('{"disposition":"uncertain"}', flush=True)""",
                            f"import os; os.write(1,{bad!r})")
    proc, _ = launch(tmp_path, driver, launcher=CAPTURE_LAUNCHER)
    assert proc.stdout.readline() == READY
    _, error = finish(proc, ACK)
    assert proc.returncode != 0, error


def test_capture_stderr_has_independent_limit(tmp_path):
    driver = STREAM.replace("ack = sys.stdin.buffer.read()",
                            "import os; os.write(2,b'x'*65537)\nack = sys.stdin.buffer.read()")
    proc, _ = launch(tmp_path, driver, launcher=CAPTURE_LAUNCHER)
    assert proc.stdout.readline() in (READY, b"")
    _, error = finish(proc, ACK)
    assert proc.returncode != 0
    assert b"stderr" in error


def test_capture_input_admitted_before_launch(tmp_path):
    launcher = CAPTURE_LAUNCHER.replace('json.dumps({"marker":sys.argv[2]})',
                                       'json.dumps({"padding":"x"*65536})')
    driver = "open(__import__('sys').argv[0]+'.unexpected','w')"
    proc, _ = launch(tmp_path, driver, launcher=launcher)
    _, error = finish(proc)
    assert b"invalid initial relay frame" in error


def test_deadline_cutoffs_and_actual_compatibility(monkeypatch):
    from exact_capture_clock import Deadline, observe_compatibility, verify_compatibility
    actual = observe_compatibility()
    assert actual["node_version"] == "v26.2.0"
    assert actual["libuv_version"] == "1.52.1"
    verify_compatibility(actual)
    with pytest.raises(ValueError):
        verify_compatibility({**actual, "time_namespace_id": "1"})
    now = time.monotonic_ns()
    deadline = Deadline(str(now + 20_000_000_000))
    monkeypatch.setattr(time, "clock_gettime_ns", lambda _: now + 6_000_000_000)
    with pytest.raises(ValueError, match="deadline"):
        deadline.remaining()
    assert deadline.remaining(5) == 9
    assert deadline.remaining(3) == 11
    assert deadline.remaining(0) == 14


def test_process_scope_inherits_absolute_cleanup_cutoffs():
    from process_lifecycle import ProcessScope
    from exact_capture_clock import Deadline
    deadline = Deadline(str(time.monotonic_ns() + 30_000_000_000))
    with ProcessScope(capture_deadline=deadline) as parent:
        with ProcessScope() as child:
            assert child.capture_deadline is deadline
            assert child.phase_cutoff(10, 5) <= deadline.expiry - 5_000_000_000
    assert not parent.errors and not child.errors


def test_expired_capture_scope_cannot_launch_child(monkeypatch):
    from process_lifecycle import ProcessScope, CleanupError
    from exact_capture_clock import Deadline
    expiry = time.monotonic_ns() + 30_000_000_000
    deadline = Deadline(str(expiry))
    with pytest.raises(CleanupError, match="aborted"), ProcessScope(capture_deadline=deadline) as scope:
        monkeypatch.setattr(time, "clock_gettime_ns", lambda _: expiry - 14_000_000_000)
        with pytest.raises(ValueError, match="deadline"):
            scope.spawn([sys.executable, "-c", "raise RuntimeError('must not launch')"])
        assert not scope.processes


def test_capture_stream_retains_only_one_frame_and_one_read(tmp_path):
    launcher = CAPTURE_LAUNCHER.replace("run_stream([", "completion = run_stream([")
    launcher += """
from dataclasses import asdict
open(sys.argv[2]+'.stats','w').write(json.dumps(asdict(completion)))
"""
    proc, marker = launch(tmp_path, STREAM, launcher=launcher)
    assert proc.stdout.readline() == READY
    _, error = finish(proc, ACK)
    assert proc.returncode == 0, error
    stats = json.loads(marker.with_suffix(".stats").read_text())
    assert stats["stdout_eof"] is True and stats["stderr_eof"] is True
    assert stats["frames"] == 35 and stats["exit_code"] == 0
    assert stats["peak_pending_bytes"] <= 65536 + 8192


def test_capture_startup_respects_work_deadline(tmp_path, monkeypatch):
    import local_chrome
    from process_lifecycle import ProcessScope, CleanupError
    from exact_capture_clock import Deadline
    expiry = time.monotonic_ns() + 30_000_000_000
    deadline = Deadline(str(expiry))
    class Browser:
        def poll(self):
            pytest.fail("expired startup must stop before accessing browser")
    with pytest.raises(CleanupError, match="aborted"), ProcessScope(capture_deadline=deadline):
        monkeypatch.setattr(time, "clock_gettime_ns", lambda _: expiry - 14_000_000_000)
        with pytest.raises(ValueError, match="deadline"):
            local_chrome._endpoint(tmp_path, Browser())


@pytest.mark.parametrize("failure", ["nonzero", "trailing", "stderr", "blocked"])
def test_terminal_or_backpressure_never_hides_transport_failure(tmp_path, failure):
    driver = STREAM
    if failure == "nonzero":
        driver += "\nraise SystemExit(7)\n"
    elif failure == "trailing":
        driver += "\nos.write(1,b'{')\n"
    elif failure == "stderr":
        driver += "\nos.write(2,b'x'*65537)\n"
    else:
        driver = DRIVER.replace(
            """print('{"disposition":"uncertain"}', flush=True)""",
            """import os
os.write(1,b'{"kind":"chunk","payload":"' + b'x'*60000 + b'"}\\n')
__import__('time').sleep(30)
""")
    proc, _ = launch(tmp_path, driver, timeout=.3, launcher=CAPTURE_LAUNCHER)
    assert proc.stdout.readline() == READY
    if failure == "blocked":
        proc.stdin.write(ACK)
        proc.stdin.close()
        proc.stdin = None
        proc.wait(timeout=4)
        _, error = finish(proc)
    else:
        _, error = finish(proc, ACK)
    assert proc.returncode != 0, error


def test_profile_release_failure_preserves_original_interrupt(tmp_path, monkeypatch):
    import os
    from profile_lease import ProfileLease
    lease = ProfileLease(tmp_path / "profile")
    lease.__enter__()
    def fail(*_args):
        raise OSError("release fsync unavailable")
    monkeypatch.setattr(os, "fsync", fail)
    original = SystemExit(143)
    with pytest.raises(SystemExit) as caught:
        lease.__exit__(SystemExit, original, None)
    assert caught.value is original
    assert isinstance(caught.value.__cause__, OSError)
    assert lease.fd is None


def test_failure_retains_actual_eof_exit_and_bounded_original_diagnostics(tmp_path):
    launcher = CAPTURE_LAUNCHER
    start = launcher.index("run_stream([")
    launcher = launcher[:start] + "try:\n" + "\n".join(
        "    " + line for line in launcher[start:].splitlines()) + """
except Exception as error:
    from dataclasses import asdict
    result = asdict(error.observations)
    result["failure"] = str(error.original_failure)
    result["diagnostics"] = error.stderr_tail.decode()
    open(sys.argv[2]+'.stats','w').write(json.dumps(result))
    raise
"""
    driver = STREAM + "\nos.write(2,b'offline original failure'); raise SystemExit(7)\n"
    proc, marker = launch(tmp_path, driver, launcher=launcher)
    assert proc.stdout.readline() == READY
    _, error = finish(proc, ACK)
    assert proc.returncode != 0
    stats = json.loads(marker.with_suffix(".stats").read_text())
    assert stats["stdout_eof"] is True and stats["stderr_eof"] is True
    assert stats["exit_code"] == 7
    assert stats["diagnostics"] == "offline original failure"
    assert "complete terminal" in stats["failure"]


@pytest.mark.parametrize("stderr_size", [0, 1])
def test_combined_output_budget_counts_every_read_byte(tmp_path, stderr_size):
    driver = """
import json,os,sys
json.loads(sys.stdin.buffer.readline())
def padded(value):
    raw=json.dumps(value).encode()
    return raw+b' '*(65535-len(raw))+b'\\n'
os.write(1,padded({"disposition":"ready_to_submit"}))
sys.stdin.buffer.read()
os.write(2,b'x'*int(sys.argv[-1]))
for _ in range(32): os.write(1,padded({"kind":"chunk"}))
os.write(1,padded({"kind":"declaration"}))
os.write(1,padded({"disposition":"uncertain"}))
"""
    launcher = CAPTURE_LAUNCHER.replace(
        '[sys.executable, "-c", sys.argv[1]]',
        f'[sys.executable, "-c", sys.argv[1], "{stderr_size}"]')
    proc, _ = launch(tmp_path, driver, timeout=5, launcher=launcher)
    initial = proc.stdout.readline()
    assert len(initial) == 65536
    assert json.loads(initial)["disposition"] == "ready_to_submit"
    output, error = finish(proc, ACK)
    if stderr_size:
        assert proc.returncode != 0
        assert b"output limit" in error
    else:
        assert proc.returncode == 0, error
        assert len(initial) + len(output) == 2293760


def test_observed_unsupported_libuv_is_not_inferred_from_node_version(monkeypatch):
    import subprocess
    import process_output
    from exact_capture_clock import observe_compatibility
    from test_capture_exchange import COMPAT, wire
    monkeypatch.setattr(process_output, "run_bounded", lambda *_args, **_kwargs:
        subprocess.CompletedProcess([], 0, wire({**COMPAT, "libuv_version": "1.0.0"}).decode(), ""))
    with pytest.raises(ValueError, match="compatibility"):
        observe_compatibility()


def test_cgroup_kill_cannot_hide_forced_cleanup_when_exit_is_immediate():
    import os
    from types import SimpleNamespace
    from exact_capture_clock import Deadline
    from process_lifecycle import ProcessScope, CleanupError
    killed = []
    before = set(os.listdir("/proc/self/fd"))
    class Handle:
        identity = (123, 1)
        def exited(self):
            return bool(killed)
        def send_signal(self, _sig):
            pass
        def reap(self):
            pass
    handle = Handle()
    scope = ProcessScope(grace=0, kill_grace=0,
                         capture_deadline=Deadline(str(time.monotonic_ns()+30_000_000_000)))
    scope.owned = {123: handle}
    scope.refresh = lambda: None
    scope.cgroup = SimpleNamespace(members=lambda: set() if killed else {123},
                                   kill=lambda: killed.append(True))
    try:
        with pytest.raises(CleanupError, match="forced escalation"):
            scope.stop()
    finally:
        if scope.capture_context is not None:
            scope.capture_context.close()
    assert set(os.listdir("/proc/self/fd")) == before


@pytest.mark.parametrize("interrupt", [SystemExit, KeyboardInterrupt])
@pytest.mark.parametrize("ownership", ["direct", "nested", "inherited"])
def test_cancelled_forced_cleanup_quarantines_owned_profile(tmp_path, monkeypatch, interrupt, ownership):
    """Real SIGTERM-ignoring child: cancellation must not erase teardown failure."""
    import contextlib
    import subprocess
    import profile_lease as leases
    from exact_capture_clock import Deadline
    from process_lifecycle import ProcessScope, CleanupError
    from test_process_lifecycle import wait_ready

    profile, ready = tmp_path / "profile", tmp_path / "ready"
    original = interrupt(143) if interrupt is SystemExit else interrupt()
    deadline = Deadline(str(time.monotonic_ns() + 30_000_000_000))
    child = None
    try:
        with pytest.raises(interrupt) as caught:
            with leases.ProfileLease(profile) as owner:
                if ownership == "inherited":
                    monkeypatch.setattr(leases, "_inherited", (profile.resolve(), owner.fd))
                borrowed = leases.ProfileLease(profile) if ownership == "inherited" else contextlib.nullcontext()
                with borrowed:
                    with ProcessScope(grace=0, kill_grace=.5, use_cgroup=False,
                                      capture_deadline=deadline) as outer:
                        nested = ProcessScope(grace=0, kill_grace=.5, use_cgroup=False) \
                            if ownership == "nested" else contextlib.nullcontext(outer)
                        with nested as scope:
                            if ownership == "nested":
                                outer.errors.append("outer teardown also unknown")
                            child = scope.spawn([sys.executable, "-c",
                                "import pathlib,signal,sys,time;"
                                "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
                                "pathlib.Path(sys.argv[1]).write_text('ready');"
                                "time.sleep(30)", str(ready)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                            wait_ready(ready)
                            raise original
        assert caught.value is original
        assert child.returncode == -9
        assert child.stdout.closed and child.stderr.closed
        assert isinstance(original.__cause__, CleanupError)
        assert "forced escalation" in str(original.__cause__)
        if ownership == "nested":
            assert "outer teardown also unknown" in str(original.__cause__)
        marker = (profile / leases.LEASE_NAME).read_bytes()
        assert b'"quarantined": true' in marker, marker
        monkeypatch.setattr(leases, "_inherited", None)
        with pytest.raises(ValueError, match="quarantined"):
            with leases.ProfileLease(profile):
                pass
    finally:
        if child is not None:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=2)


@pytest.mark.parametrize("interrupt", ["SystemExit(143)", "KeyboardInterrupt()"])
def test_inherited_worker_quarantine_survives_clean_supervisor_cleanup(tmp_path, interrupt):
    import os
    import subprocess
    from profile_lease import ProfileLease, LEASE_NAME
    from process_lifecycle import ProcessScope, CleanupError
    from exact_capture_clock import Deadline

    profile = tmp_path / "profile"
    source = """
import json, select, subprocess, sys, time
from profile_lease import ProfileLease, inherit_lease
from process_lifecycle import ProcessScope, cleanup_failure
from exact_capture_clock import Deadline
inherit_lease(sys.argv[1], int(sys.argv[2]))
original = INTERRUPT
try:
    with ProfileLease(sys.argv[1]):
        with ProcessScope(grace=0, kill_grace=.5, use_cgroup=False,
                          capture_deadline=Deadline(sys.argv[3])) as scope:
            child = scope.spawn([sys.executable, '-c',
                "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);"
                "print('ready',flush=True);time.sleep(30)"], stdout=subprocess.PIPE)
            assert select.select([child.stdout], [], [], 3)[0]
            assert child.stdout.readline() == b'ready\\n'
            raise original
except (SystemExit, KeyboardInterrupt) as caught:
    assert caught is original
    assert child.returncode == -9
    assert 'forced escalation' in str(cleanup_failure(caught))
    print(json.dumps({'identity_preserved': True, 'child_exit': child.returncode}))
""".replace("INTERRUPT", interrupt)
    deadline = Deadline(str(time.monotonic_ns() + 30_000_000_000))
    with pytest.raises(CleanupError, match="nested owner"):
        with ProfileLease(profile) as lease:
            with ProcessScope(capture_deadline=deadline) as supervisor:
                worker = supervisor.spawn(
                    [sys.executable, "-c", source, str(profile), str(lease.fd), str(deadline.expiry)],
                    pass_fds=(lease.fd,), env={**os.environ, "PYTHONPATH": str(SCRIPTS)},
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                output, error = worker.communicate(timeout=5)
                assert worker.returncode == 0, error
                assert json.loads(output) == {"identity_preserved": True, "child_exit": -9}
    assert not supervisor.errors
    assert b'"quarantined": true' in (profile / LEASE_NAME).read_bytes()
    with pytest.raises(ValueError, match="quarantined"):
        with ProfileLease(profile):
            pass


@pytest.mark.parametrize("stubborn", [False, True])
@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("unwinding", ["none", "exit", "keyboard"])
def test_signal_first_delivered_during_cleanup_preserves_cancellation(
        tmp_path, stubborn, nested, unwinding):
    import contextlib
    import select
    import subprocess
    from profile_lease import ProfileLease
    from process_lifecycle import ProcessScope, cleanup_failure
    from exact_capture_clock import Deadline

    original = {"none": None, "exit": SystemExit(99), "keyboard": KeyboardInterrupt()}[unwinding]
    seen = []
    @contextlib.contextmanager
    def observe():
        try:
            yield
        except BaseException as exc:
            seen.append(exc)
            raise

    deadline = Deadline(str(time.monotonic_ns() + 30_000_000_000))
    profile = tmp_path / "profile"
    child = None
    code = """
import os, signal, time
def term(*_):
    os.kill(os.getppid(), signal.SIGTERM)
    if not STUBBORN:
        raise SystemExit(0)
signal.signal(signal.SIGTERM, term)
print('ready', flush=True)
while True: time.sleep(.01)
""".replace("STUBBORN", repr(stubborn))
    try:
        with pytest.raises((SystemExit, KeyboardInterrupt)) as caught:
            with ProfileLease(profile):
                with ProcessScope(grace=.1, kill_grace=.5, use_cgroup=False,
                                  capture_deadline=deadline) as outer:
                    with observe():
                        inner = ProcessScope(grace=.1, kill_grace=.5, use_cgroup=False) \
                            if nested else contextlib.nullcontext(outer)
                        with inner as owner:
                            child = owner.spawn([sys.executable, "-c", code], stdout=subprocess.PIPE)
                            assert select.select([child.stdout], [], [], 3)[0]
                            assert child.stdout.readline() == b"ready\n"
                            if original is not None:
                                raise original
        if original is None:
            assert isinstance(caught.value, SystemExit)
            assert caught.value.code == 143
        else:
            assert caught.value is original
        if nested:
            assert seen == [caught.value], "nested owner replaced pending cancellation"
        assert child.returncode == (-9 if stubborn else 0)
        if stubborn:
            assert "forced escalation" in str(cleanup_failure(caught.value))
            with pytest.raises(ValueError, match="quarantined"):
                with ProfileLease(profile):
                    pass
        else:
            assert cleanup_failure(caught.value) is None
            with ProfileLease(profile):
                pass
    finally:
        if child is not None:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=2)


@pytest.mark.parametrize("late", ["frames", "stdout_limit", "stderr_limit"])
def test_failed_relay_observes_cleanup_without_admitting_late_output(tmp_path, late):
    launcher = CAPTURE_LAUNCHER.replace("grace=.1", "grace=.6")
    start = launcher.index("run_stream([")
    launcher = launcher[:start] + "try:\n" + "\n".join(
        "    " + line for line in launcher[start:].splitlines()) + """
except Exception as error:
    from dataclasses import asdict
    from process_lifecycle import cleanup_failure
    stats = asdict(error.observations)
    stats["original"] = str(error.original_failure)
    stats["cleanup"] = str(cleanup_failure(error))
    stats["diagnostic_bytes"] = len(error.stderr_tail)
    open(sys.argv[2]+'.stats','w').write(json.dumps(stats))
    raise
"""
    driver = DRIVER.replace("""print('{"disposition":"uncertain"}', flush=True)""", """
import os,time
print('{"bad":"frame"}',flush=True)
time.sleep(.15)
LATE
open(request["marker"]+'.closed','w').write('yes')
""")
    late_output = {
        "frames": "os.write(1,b'{\"kind\":\"declaration\"}\\n{\"disposition\":\"uncertain\"}\\n')",
        "stdout_limit": "os.write(1,b'x'*2293761)",
        "stderr_limit": "os.write(2,b'x'*65537)",
    }[late]
    proc, marker = launch(tmp_path, driver.replace("LATE", late_output), timeout=3, launcher=launcher)
    assert proc.stdout.readline() == READY
    output, error = finish(proc, ACK)
    assert proc.returncode != 0, error
    assert output == b"", "late frames escaped failed observation mode"
    assert marker.with_suffix(".closed").exists(), "child cleanup preempted"
    stats = json.loads(marker.with_suffix(".stats").read_text())
    assert stats["original"] == "bad frame"
    assert "unknown" in stats["cleanup"]
    assert stats["exit_code"] == 0
    assert stats["stdout_bytes"] + stats["stderr_bytes"] <= 2293761
    assert stats["stderr_bytes"] <= 65537
    assert stats["diagnostic_bytes"] <= 1024
    if late == "frames":
        assert stats["stdout_eof"] and stats["stderr_eof"]


def test_work_expiry_freezes_acknowledgment_during_cleanup_observation(tmp_path):
    from test_process_lifecycle import wait_ready
    launcher = CAPTURE_LAUNCHER.replace("grace=.1", "grace=.6")
    driver = r"""
import json,sys,time
request=json.loads(sys.stdin.buffer.readline())
print('{"disposition":"ready_to_submit"}',flush=True)
raw=sys.stdin.buffer.read()
open(request["marker"]+'.ack','wb').write(raw)
time.sleep(.2)
if raw == b'{"disposition":"submit_acknowledged"}\n':
    open(request["marker"],'w').write('unexpected effect')
print('{"disposition":"uncertain"}',flush=True)
open(request["marker"]+'.closed','w').write('yes')
"""
    proc, marker = launch(tmp_path, driver, timeout=.2, launcher=launcher)
    assert proc.stdout.readline() == READY
    wait_ready(marker.with_suffix(".ack"))
    output, error = finish(proc, ACK)
    assert proc.returncode != 0, error
    assert output == b""
    assert marker.with_suffix(".ack").read_bytes() == b""
    assert marker.with_suffix(".closed").exists()
    assert not marker.exists()


def test_capture_cleanup_observation_and_stop_share_original_phase_budget(monkeypatch):
    import os
    from process_lifecycle import ProcessScope
    from exact_capture_clock import Deadline
    now = time.monotonic_ns()
    deadline = Deadline(str(now + 17_000_000_000))
    monkeypatch.setattr(time, "clock_gettime_ns", lambda _: now + 2_000_000_000)
    worker = ProcessScope(capture_deadline=deadline)
    supervisor = ProcessScope(capture_deadline=deadline, outer_capture=True)
    before = set(os.listdir("/proc/self/fd"))
    try:
        worker_cutoffs = worker.begin_cleanup()
        supervisor_cutoffs = supervisor.begin_cleanup()
        assert worker_cutoffs == (now + 12_000_000_000, now + 14_000_000_000)
        assert supervisor_cutoffs == (now + 14_000_000_000, now + 16_000_000_000)
        monkeypatch.setattr(time, "clock_gettime_ns", lambda _: now + 13_000_000_000)
        assert worker.begin_cleanup() == worker_cutoffs
        assert supervisor.begin_cleanup() == supervisor_cutoffs
    finally:
        try:
            if worker.capture_context is not None:
                worker.capture_context.close()
        finally:
            if supervisor.capture_context is not None:
                supervisor.capture_context.close()
    assert set(os.listdir("/proc/self/fd")) == before


def test_sequential_nested_capture_owners_share_first_cleanup_cutoffs(tmp_path, monkeypatch):
    from process_lifecycle import ProcessScope
    from exact_capture_clock import Deadline
    now = time.monotonic_ns()
    observed_now = [now]
    monkeypatch.setattr(time, "clock_gettime_ns", lambda _: observed_now[0])
    deadline = Deadline(str(now + 60_000_000_000))
    with ProcessScope(capture_deadline=deadline, use_cgroup=False) as worker:
        with ProcessScope(use_cgroup=False) as node:
            node_cutoffs = node.begin_cleanup()
        observed_now[0] += 4_000_000_000
        with ProcessScope(use_cgroup=False) as chrome:
            chrome_cutoffs = chrome.begin_cleanup()
        with ProcessScope(use_cgroup=False) as display:
            display_cutoffs = display.begin_cleanup()
        worker_cutoffs = worker.begin_cleanup()
    facts = {"node": node_cutoffs, "chrome": chrome_cutoffs,
             "display": display_cutoffs, "worker": worker_cutoffs}
    (tmp_path / "cutoffs.json").write_text(json.dumps(facts, indent=2))
    assert all(value == node_cutoffs for value in facts.values()), facts
