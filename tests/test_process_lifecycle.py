"""Offline lifecycle probes: real subprocesses, no browser or network."""
import contextlib
import importlib
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import time

import pytest

from test_exact_worker import SCRIPTS, fake_runtime, fake_chrome, alive, clean_pids
import exact_worker
import local_chrome
import post_linkedin


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    for key in (local_chrome.CHROME_ENV, local_chrome.PROFILE_ENV, local_chrome.XVFB_ENV):
        monkeypatch.delenv(key, raising=False)


def test_node_driver_rejects_eight_megabytes_before_success(tmp_path):
    node = tmp_path / "fake-node"
    node.write_text(f"""#!{sys.executable}
import os
os.write(2, b'x' * (8 * 1024 * 1024))
print('{{"disposition":"preview_verified"}}')
""")
    node.chmod(0o755)
    with pytest.raises(ValueError, match="output limit"):
        post_linkedin._drive(str(node), {})


def test_setsid_grandchild_is_reaped_but_preexisting_child_survives(tmp_path):
    pids = tmp_path / "escaped-pid"
    runtime = fake_runtime(tmp_path, f"""
import os, signal, time
def main():
    if os.fork() == 0:
        os.setsid()
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        open({str(pids)!r}, 'w').write(str(os.getpid()))
        while True: time.sleep(.02)
    while True: time.sleep(.02)
""")
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        with pytest.raises(ValueError, match="timed out"):
            exact_worker.run_worker(runtime, {}, timeout=.4, grace=.1)
        assert pids.exists()
        assert not alive(int(pids.read_text())), "setsid descendant escaped ownership"
        assert unrelated.poll() is None
    finally:
        unrelated.kill()
        unrelated.wait()
        clean_pids(pids)


def test_completed_worker_never_signals_retired_numeric_pid(tmp_path, monkeypatch):
    runtime = fake_runtime(tmp_path, """
def main():
    print('{"disposition":"preview_verified"}')
""")
    real_killpg = os.killpg
    signalled = []

    def record_group(pid, sig):
        if sig != 0:
            signalled.append((pid, sig))
        return real_killpg(pid, sig)

    monkeypatch.setattr(os, "killpg", record_group)
    assert exact_worker.run_worker(runtime, {}, timeout=2)["disposition"] == "preview_verified"
    assert signalled == [], "completed worker's PID was signalled after being reaped"


def test_cleanup_attempts_other_children_and_closes_pipes_on_target_failure(tmp_path, monkeypatch):
    lifecycle = importlib.import_module("process_lifecycle")
    attempts = []
    streams = []
    children = []
    real_send = lifecycle.ProcessHandle.send_signal

    def fail_first(handle, sig):
        attempts.append(handle.pid)
        if handle.pid == children[0].pid:
            raise PermissionError("injected target failure")
        return real_send(handle, sig)

    try:
        with pytest.raises(lifecycle.CleanupError, match="injected target failure"):
            with lifecycle.ProcessScope(grace=.05, kill_grace=.1) as scope:
                for _ in range(2):
                    proc = scope.spawn([sys.executable, "-c", "import time; time.sleep(30)"],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    children.append(proc)
                    streams.extend((proc.stdout, proc.stderr))
                monkeypatch.setattr(lifecycle.ProcessHandle, "send_signal", fail_first)
        assert children[1].pid in attempts
        assert not alive(children[1].pid)
        assert all(stream.closed for stream in streams)
    finally:
        for proc in children:
            if proc.poll() is None:
                proc.kill()
            proc.wait()


def test_failed_browser_teardown_quarantines_profile_without_singleton(tmp_path, monkeypatch):
    lifecycle = importlib.import_module("process_lifecycle")
    profile = tmp_path / "profile"
    chrome = tmp_path / "fake-chrome"
    chrome.write_text(f"""#!{sys.executable}
import pathlib, sys, time
p = pathlib.Path(next(a.split('=',1)[1] for a in sys.argv if a.startswith('--user-data-dir=')))
(p / 'DevToolsActivePort').write_text('1234\\n/devtools/browser/fake')
while True: time.sleep(.02)
""")
    chrome.chmod(0o755)
    monkeypatch.setenv(local_chrome.PROFILE_ENV, str(profile))
    monkeypatch.setattr(local_chrome, "STOP_S", .05)
    real_send = lifecycle.ProcessHandle.send_signal
    child = []

    def fail(handle, sig):
        child.append(handle.pid)
        raise PermissionError("cannot stop owned Chrome")

    try:
        with pytest.raises(lifecycle.CleanupError):
            with local_chrome.devtools_endpoint(str(chrome)):
                monkeypatch.setattr(lifecycle.ProcessHandle, "send_signal", fail)
        assert child
        assert not (profile / "SingletonLock").exists()
        # Refusal must persist even after original owner exits / flock releases.
        code = "import pathlib,local_chrome,sys\nwith local_chrome.profile_lease(pathlib.Path(sys.argv[1])): pass"
        result = subprocess.run([sys.executable, "-c", code, str(profile)],
                                env={**os.environ, "PYTHONPATH": str(SCRIPTS)},
                                capture_output=True, timeout=3)
        assert result.returncode != 0
        assert b"quarantined" in result.stderr
    finally:
        monkeypatch.setattr(lifecycle.ProcessHandle, "send_signal", real_send)
        for pid in set(child):
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)
            with contextlib.suppress(ChildProcessError):
                os.waitpid(pid, 0)


def test_status_probe_failure_does_not_skip_other_targets_or_pipes(monkeypatch):
    lifecycle = importlib.import_module("process_lifecycle")
    children, streams = [], []
    exited = lifecycle.ProcessHandle.exited

    def fail_status(handle):
        if handle.pid == children[0].pid:
            raise OSError("injected pidfd status failure")
        return exited(handle)

    try:
        with pytest.raises(lifecycle.CleanupError, match="status failure"):
            with lifecycle.ProcessScope(grace=.02, kill_grace=.05) as scope:
                for _ in range(2):
                    proc = scope.spawn([sys.executable, "-c", "import time; time.sleep(30)"],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    children.append(proc)
                    streams.extend((proc.stdout, proc.stderr))
                monkeypatch.setattr(lifecycle.ProcessHandle, "exited", fail_status)
        assert not alive(children[1].pid)
        assert all(stream.closed for stream in streams)
    finally:
        monkeypatch.setattr(lifecycle.ProcessHandle, "exited", exited)
        for proc in children:
            if proc.poll() is None:
                proc.kill()
            proc.wait()


def test_singleton_cleanup_attempts_all_files_and_quarantines(tmp_path, monkeypatch):
    leases = importlib.import_module("profile_lease")
    lifecycle = importlib.import_module("process_lifecycle")
    profile = tmp_path / "profile"
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    profile.mkdir()
    (profile / "SingletonLock").symlink_to(f"fake-{child.pid}")
    for name in ("SingletonSocket", "SingletonCookie", "DevToolsActivePort"):
        (profile / name).touch()
    unlink = Path.unlink

    def fail_one(path, *args, **kwargs):
        if path.name == "SingletonSocket":
            raise PermissionError("injected socket unlink failure")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_one)
    with pytest.raises(lifecycle.CleanupError, match="socket unlink failure"):
        with leases.ProfileLease(profile) as lease:
            lease.clean_singleton({(child.pid, 0)})
    assert not (profile / "SingletonCookie").exists()
    assert not (profile / "DevToolsActivePort").exists()
    with pytest.raises(ValueError, match="quarantined"):
        with leases.ProfileLease(profile):
            pass


def test_quarantine_survives_owner_exit_even_if_failure_marker_write_fails(tmp_path):
    profile = tmp_path / "profile"
    source = """
import os, sys
from profile_lease import ProfileLease
from process_lifecycle import CleanupError
with ProfileLease(sys.argv[1]):
    def fail(*args, **kwargs):
        raise OSError("disk stopped accepting writes")
    os.pwrite = fail
    raise CleanupError(["owned browser could not stop"])
"""
    proc = subprocess.run([sys.executable, "-c", source, str(profile)],
                          env={**os.environ, "PYTHONPATH": str(SCRIPTS)},
                          capture_output=True, timeout=3)
    assert proc.returncode != 0
    with pytest.raises(ValueError, match="quarantined"):
        with local_chrome.profile_lease(profile):
            pass


def test_pidfd_signal_never_uses_reassigned_numeric_pid():
    lifecycle = importlib.import_module("process_lifecycle")
    own = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    handle = lifecycle.ProcessHandle(own.pid, own)
    try:
        # Deterministically simulate reassignment of the numeric identifier.
        # Only the captured generation's pidfd may control the actual target.
        handle.pid = unrelated.pid
        handle.send_signal(signal.SIGTERM)
        own.wait(timeout=2)
        assert unrelated.poll() is None
        handle.send_signal(signal.SIGKILL)  # retired generation must be a no-op
        assert unrelated.poll() is None
    finally:
        handle.close()
        for proc in (own, unrelated):
            if proc.poll() is None:
                proc.kill()
            proc.wait()


def test_worker_quarantine_cannot_be_cleared_by_successful_parent_exit(tmp_path, monkeypatch):
    lifecycle = importlib.import_module("process_lifecycle")
    profile = tmp_path / "profile"
    monkeypatch.setenv(local_chrome.PROFILE_ENV, str(profile))
    monkeypatch.setenv(local_chrome.CHROME_ENV, "unused-fake")
    runtime = fake_runtime(tmp_path, """
import os, sys
def main():
    # Simulate a nested owner's persisted teardown failure.
    fd = int(sys.argv[2])
    os.pwrite(fd, b'{"quarantined":true}', 0)
    os.fsync(fd)
    print('{"disposition":"preview_verified"}')
""")
    with pytest.raises(lifecycle.CleanupError, match="quarantined"):
        exact_worker.run_worker(runtime, {}, timeout=2)
    with pytest.raises(ValueError, match="quarantined"):
        with local_chrome.profile_lease(profile):
            pass


def supervisor_fixture(tmp_path):
    lifecycle = importlib.import_module("process_lifecycle")
    profile = tmp_path / "profile"
    chrome = fake_chrome(tmp_path, stubborn=True)
    ready = tmp_path / "ready"
    runtime = fake_runtime(tmp_path, f"""
import local_chrome, os, signal, time
def main():
    with local_chrome.devtools_endpoint(local_chrome.configured_chrome()):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        open({str(ready)!r}, 'w').write(str(os.getpid()))
        while True: time.sleep(.02)
""")
    env = {**os.environ, "PYTHONPATH": str(SCRIPTS),
           local_chrome.PROFILE_ENV: str(profile), local_chrome.CHROME_ENV: str(chrome)}
    args = [sys.executable, "-c",
            "from pathlib import Path; from exact_worker import run_worker; import sys; "
            "run_worker(Path(sys.argv[1]), {}, timeout=230)", str(runtime)]
    return lifecycle, profile, ready, args, env


def wait_ready(ready):
    deadline = time.monotonic() + 3
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(.01)
    assert ready.exists()


def test_default_supervisor_term_escalation_fits_gateway_fifteen_second_grace(tmp_path):
    lifecycle, profile, ready, args, env = supervisor_fixture(tmp_path)
    # Test guard cleans fixtures if an assertion fails; assertions below run
    # before guard teardown, so it cannot mask the publisher's lifecycle result.
    with lifecycle.ProcessScope(grace=.1) as guard:
        proc = guard.spawn(args, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        wait_ready(ready)
        worker_pid = int(ready.read_text())
        chrome_pid = int((profile / "pids").read_text())
        started = time.monotonic()
        proc.terminate()
        _, stderr = proc.communicate(timeout=14.5)
        elapsed = time.monotonic() - started
        assert proc.returncode == 143, stderr
        assert elapsed < 14.5, f"exceeded gateway cancellation budget: {elapsed}"
        assert not alive(worker_pid)
        assert not alive(chrome_pid)
        with local_chrome.profile_lease(profile):
            pass
        assert not (profile / "SingletonLock").is_symlink()


def test_abrupt_supervisor_kill_quarantines_after_all_lease_fds_close(tmp_path):
    lifecycle, profile, ready, args, env = supervisor_fixture(tmp_path)
    with lifecycle.ProcessScope(grace=.1) as guard:
        proc = guard.spawn(args, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        wait_ready(ready)
        worker_pid = int(ready.read_text())
        chrome_pid = int((profile / "pids").read_text())
        proc.kill()
        proc.wait(timeout=2)
        # SIGKILL cannot execute Python cleanup. Do not pretend that the gateway
        # owns detached descendants: they can remain alive, but profile is held.
        assert alive(worker_pid)
        assert alive(chrome_pid)
        with pytest.raises(ValueError, match="active|quarantined"):
            with local_chrome.profile_lease(profile):
                pass
    # Guard has now reaped the fixture descendants and closed their inherited
    # lease descriptors. Persistent quarantine must still block a fresh run.
    assert not alive(worker_pid)
    assert not alive(chrome_pid)
    with pytest.raises(ValueError, match="quarantined"):
        with local_chrome.profile_lease(profile):
            pass


def test_delegated_cgroup_contains_setsid_tree_and_is_removed(tmp_path):
    lifecycle = importlib.import_module("process_lifecycle")
    pids = tmp_path / "child-pid"
    with lifecycle.ProcessScope(grace=.05) as scope:
        if scope.cgroup is None:
            pytest.skip("host does not delegate cgroup-v2 containment")
        group_path = scope.cgroup.path
        code = f"""
import os, signal, time
if os.fork() == 0:
    os.setsid()
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    open({str(pids)!r}, 'w').write(str(os.getpid()))
while True: time.sleep(.02)
"""
        proc = scope.spawn([sys.executable, "-c", code])
        wait_ready(pids)
        child = int(pids.read_text())
        membership = Path(f"/proc/{child}/cgroup").read_text()
        assert scope.cgroup.relative in membership
    assert not alive(proc.pid)
    assert not alive(child)
    assert not group_path.exists()


def test_pidfd_fallback_reaps_double_fork_setsid_child(tmp_path):
    lifecycle = importlib.import_module("process_lifecycle")
    pids = tmp_path / "child-pid"
    code = f"""
import os, signal, time
if os.fork() == 0:
    if os.fork() == 0:
        os.setsid()
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        open({str(pids)!r}, 'w').write(str(os.getpid()))
        while True: time.sleep(.02)
    os._exit(0)
while True: time.sleep(.02)
"""
    try:
        with lifecycle.ProcessScope(grace=.05, use_cgroup=False) as scope:
            proc = scope.spawn([sys.executable, "-c", code])
            wait_ready(pids)
        assert not alive(proc.pid)
        assert not alive(int(pids.read_text()))
    finally:
        clean_pids(pids)


def test_nested_cgroup_disappearance_during_cleanup_is_not_failure(monkeypatch):
    lifecycle = importlib.import_module("process_lifecycle")
    with lifecycle.ProcessScope(grace=.05) as scope:
        if scope.cgroup is None:
            pytest.skip("host does not delegate cgroup-v2 containment")
        child = scope.cgroup.path / "finished-nested-owner"
        child.mkdir()
        scandir = os.scandir

        def disappear(path):
            if Path(path) == child and child.exists():
                child.rmdir()
            return scandir(path)

        monkeypatch.setattr(os, "scandir", disappear)
        scope.refresh()
        assert not child.exists()


def test_fallback_refuses_stale_admission_snapshot_after_unrelated_fork_exit():
    # Run in a clean interpreter so the probe controls every child and adoption.
    # Interleave a REAL fork/setsid/exit between observing a pre-existing child
    # and returning the root-children snapshot to fallback admission.
    source = r'''
import contextlib, json, os, signal, subprocess, sys
import process_lifecycle as lifecycle

go_read, go_write = os.pipe()
ready_read, ready_write = os.pipe()
code = """
import os, signal, sys, time
os.read(int(sys.argv[1]), 1)
if os.fork() == 0:
    os.setsid()
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    os.write(int(sys.argv[2]), (str(os.getpid()) + '\\n').encode())
    while True: time.sleep(.02)
os._exit(0)
"""
outsider = subprocess.Popen([sys.executable, "-c", code, str(go_read), str(ready_write)],
                           pass_fds=(go_read, ready_write))
os.close(go_read)
os.close(ready_write)
children = lifecycle.ProcessHandle.children
grandchild = None
interleaved = False
def fork_exit_during_snapshot(handle):
    global grandchild, interleaved
    snapshot = children(handle)
    if handle.pid == os.getpid() and outsider.pid in snapshot and not interleaved:
        interleaved = True
        os.write(go_write, b'x')
        with os.fdopen(ready_read) as ready:
            grandchild = int(ready.readline())
        outsider.wait(timeout=2)
    return snapshot

lifecycle.ProcessHandle.children = fork_exit_during_snapshot
entered = refused = survived = False
try:
    try:
        with lifecycle.ProcessScope(grace=.02, kill_grace=.1, use_cgroup=False) as scope:
            entered = True
            scope.refresh()
    except RuntimeError as exc:
        refused = "preexisting" in str(exc)
    survived = grandchild is not None and os.path.exists(f"/proc/{grandchild}")
finally:
    lifecycle.ProcessHandle.children = children
    os.close(go_write)
    if outsider.poll() is None:
        outsider.kill()
    outsider.wait()
    if grandchild is not None:
        with contextlib.suppress(ProcessLookupError):
            os.kill(grandchild, signal.SIGKILL)
        with contextlib.suppress(ChildProcessError):
            os.waitpid(grandchild, 0)
print(json.dumps(dict(entered=entered, refused=refused, survived=survived,
                     interleaved=interleaved)))
'''
    probe = subprocess.run([sys.executable, "-c", source],
                           env={**os.environ, "PYTHONPATH": str(SCRIPTS)},
                           capture_output=True, text=True, timeout=5)
    assert probe.returncode == 0, probe.stderr
    assert json.loads(probe.stdout) == {
        "entered": False, "refused": True, "survived": True, "interleaved": True,
    }


def test_nested_fallback_refuses_before_node_launch(tmp_path, monkeypatch):
    lifecycle = importlib.import_module("process_lifecycle")
    marker = tmp_path / "node-launched"
    node = tmp_path / "fake-node"
    node.write_text(f"#!{sys.executable}\nopen({str(marker)!r}, 'w').write('launched')\nprint('{{}}')\n")
    node.chmod(0o755)
    monkeypatch.setattr(lifecycle.OwnedCgroup, "create", lambda parent=None: None)
    with lifecycle.ProcessScope(grace=.05, use_cgroup=False) as outer:
        existing = outer.spawn([sys.executable, "-c", "import time; time.sleep(30)"])
        with pytest.raises(RuntimeError, match="preexisting"):
            post_linkedin._drive(str(node), {})
        assert existing.poll() is None
        assert not marker.exists()
    assert not alive(existing.pid)


def test_active_lease_syncs_containing_directory_before_launch(tmp_path, monkeypatch):
    leases = importlib.import_module("profile_lease")
    profile = tmp_path / "profile"
    synced_directories = []
    fsync = os.fsync

    def record_fsync(fd):
        info = os.fstat(fd)
        if stat.S_ISDIR(info.st_mode):
            synced_directories.append((info.st_dev, info.st_ino))
        return fsync(fd)

    monkeypatch.setattr(os, "fsync", record_fsync)
    with leases.ProfileLease(profile):
        info = profile.stat()
        assert (info.st_dev, info.st_ino) in synced_directories
