"""Offline process regressions: no Chrome, network, or model calls."""
import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

SCRIPTS = Path(__file__).parents[1] / "social/linkedin-post/scripts"
sys.path.insert(0, str(SCRIPTS))
import exact_protocol
import local_chrome
import process_lifecycle


@pytest.fixture(autouse=True)
def offline_environment(monkeypatch):
    for key in (local_chrome.CHROME_ENV, local_chrome.PROFILE_ENV, local_chrome.XVFB_ENV):
        monkeypatch.delenv(key, raising=False)


def worker():
    return importlib.import_module("exact_worker")


def fake_runtime(tmp_path, source):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    # Actual lifecycle code, with an offline preview implementation.
    for name in ("exact_worker.py", "local_chrome.py", "process_lifecycle.py",
                 "process_output.py", "profile_lease.py", "process_cgroup.py"):
        if (SCRIPTS / name).exists():
            (runtime / name).write_bytes((SCRIPTS / name).read_bytes())
    (runtime / "exact_preview.py").write_text(source)
    return runtime


def protocol(body, monkeypatch):
    stdin = io.TextIOWrapper(io.BytesIO(body), encoding="utf-8")
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)
    exact_protocol.main(["--protocol", "storyproof.linkedin/1"])
    return json.loads(stdout.getvalue())


@pytest.mark.parametrize("body", [
    b'{"request_id":"\\ud800"}',
    b'{"request_id":[]}',
    b'{"request_id":"unsafe id"}',
    b"\xff",
    b"[" * 10000 + b"]" * 10000,
])
def test_malformed_envelope_has_safe_null_request_id(body, monkeypatch):
    result = protocol(body, monkeypatch)
    assert result["disposition"] == "refused_pre_effect"
    assert result["request_id"] is None
    json.dumps(result, ensure_ascii=False).encode("utf-8")


@pytest.mark.parametrize("failure", [RecursionError("deep"), OverflowError("large")])
def test_admission_resource_errors_are_json(failure, monkeypatch):
    def reject(*args, **kwargs):
        raise failure
    monkeypatch.setattr(exact_protocol, "admit", reject)
    result = protocol(b'{"request_id":"safe-id"}', monkeypatch)
    assert result["request_id"] == "safe-id"
    assert result["disposition"] == "refused_pre_effect"


def test_isolated_worker_ignores_hostile_python_startup(tmp_path, monkeypatch):
    marker = tmp_path / "executed"
    userbase = tmp_path / "userbase"
    site = userbase / f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages"
    site.mkdir(parents=True)
    payload = f"open({str(marker)!r}, 'a').write('executed')"
    (site / "usercustomize.py").write_text(payload)
    (site / "hostile.pth").write_text("import os; " + payload + "\n")
    hostile = tmp_path / "hostile"
    hostile.mkdir()
    (hostile / "sitecustomize.py").write_text(payload)
    (hostile / "exact_preview.py").write_text(payload)
    control_env = {key: value for key, value in os.environ.items() if not key.startswith("PYTHON")}
    control_env.update(PYTHONUSERBASE=str(userbase), PYTHONPATH=str(hostile))
    subprocess.run([sys.executable, "-c", "pass"], env=control_env, check=True, timeout=3)
    assert marker.exists(), "hostile startup fixture must execute without isolation"
    marker.unlink()
    monkeypatch.setenv("PYTHONUSERBASE", str(userbase))
    monkeypatch.setenv("PYTHONPATH", str(hostile))
    monkeypatch.setenv("PYTHONHOME", str(tmp_path / "nonexistent-python"))
    runtime = fake_runtime(tmp_path, """
import json, os, sys
def main():
    print(json.dumps({"disposition": "preview_verified", "path": sys.path,
                      "site_loaded": "site" in sys.modules,
                      "python_env": [k for k in os.environ if k.startswith("PYTHON")]}))
""")
    result = worker().run_worker(runtime, {}, timeout=3)
    assert not marker.exists()
    assert result["site_loaded"] is False
    assert result["python_env"] == []
    assert result["path"][0] == str(runtime)
    assert str(hostile) not in result["path"]
    assert "" not in result["path"]


@pytest.mark.parametrize("source", [
    "print('[]')",
    "print('null')",
    "print('{\"disposition\":\"published\"}')",
    "print('{\"disposition\":\"preview_verified\",\"v\":NaN}')",
    "import os; os.write(1, b'\\xff')",
    "print('[' * 2000 + ']' * 2000)",
    "print('x' * (2 * 1024 * 1024))",
    "import sys; sys.stderr.write('x' * (2 * 1024 * 1024)); print('{}')",
])
def test_worker_output_is_bounded_valid_object(tmp_path, source):
    runtime = fake_runtime(tmp_path, "def main():\n    " + source + "\n")
    with pytest.raises(ValueError):
        worker().run_worker(runtime, {}, timeout=3)


def alive(pid):
    return Path(f"/proc/{pid}").exists()


def clean_pids(path):
    if path.exists():
        for pid in map(int, path.read_text().split()):
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)
            with contextlib.suppress(ChildProcessError):
                os.waitpid(pid, 0)


def fake_chrome(tmp_path, *, startup=True, stubborn=False):
    path = tmp_path / "fake-chrome"
    path.write_text(f"""#!{sys.executable}
import os, pathlib, signal, sys, time
profile = pathlib.Path(next(x.split('=', 1)[1] for x in sys.argv if x.startswith('--user-data-dir=')))
profile.mkdir(exist_ok=True)
(profile / 'SingletonLock').symlink_to('fakehost-' + str(os.getpid()))
(profile / 'pids').write_text(str(os.getpid()) + '\\n')
if {stubborn!r}:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
if {startup!r}:
    (profile / 'DevToolsActivePort').write_text('1234\\n/devtools/browser/fake')
while True:
    time.sleep(.05)
""")
    path.chmod(0o755)
    return path


def test_atomic_profile_lease_refuses_run_login_and_leftover_cleanup(tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    monkeypatch.setenv(local_chrome.PROFILE_ENV, str(profile))
    chrome = fake_chrome(tmp_path)
    with local_chrome.devtools_endpoint(str(chrome)):
        pid = int((profile / "pids").read_text())
        for action in (
            "with local_chrome.devtools_endpoint(sys.argv[1]): pass",
            "local_chrome.login(sys.argv[1], pathlib.Path(sys.argv[2]))",
            "local_chrome.end_leftover_run(pathlib.Path(sys.argv[2]))",
        ):
            code = "import local_chrome, pathlib, sys\n" + action
            proc = subprocess.run([sys.executable, "-c", code, str(chrome), str(profile)],
                                  env={**os.environ, "PYTHONPATH": str(SCRIPTS)},
                                  capture_output=True, timeout=3)
            assert proc.returncode != 0
            assert b"profile already active" in proc.stderr
            assert alive(pid)
    assert not alive(pid)
    assert not (profile / "SingletonLock").is_symlink()
    with local_chrome.devtools_endpoint(str(chrome)):
        pass


@pytest.mark.parametrize("startup", [False, True])
def test_timeout_cleans_detached_chrome_and_profile(tmp_path, monkeypatch, startup):
    profile = tmp_path / "profile"
    chrome = fake_chrome(tmp_path, startup=startup, stubborn=True)
    monkeypatch.setenv(local_chrome.PROFILE_ENV, str(profile))
    monkeypatch.setenv(local_chrome.CHROME_ENV, str(chrome))
    runtime = fake_runtime(tmp_path, """
import local_chrome, time
def main():
    local_chrome.STOP_S = .15
    with local_chrome.devtools_endpoint(local_chrome.configured_chrome()):
        time.sleep(30)
""")
    try:
        with pytest.raises(ValueError, match="timed out"):
            worker().run_worker(runtime, {}, timeout=.7, grace=1)
        pids = list(map(int, (profile / "pids").read_text().split()))
        assert all(not alive(pid) for pid in pids)
        assert not (profile / "SingletonLock").is_symlink()
        with local_chrome.profile_lease(profile):
            pass
    finally:
        clean_pids(profile / "pids")


def test_stop_reaps_stubborn_descendant_after_group_leader_exits(tmp_path, monkeypatch):
    pids = tmp_path / "pids"
    monkeypatch.setattr(local_chrome, "STOP_S", .15)
    code = """
import os, signal, sys, time
child = os.fork()
if child == 0:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    open(sys.argv[1], 'w').write(str(os.getpid()))
    while True: time.sleep(.05)
while not os.path.exists(sys.argv[1]): time.sleep(.01)
"""
    try:
        with local_chrome.owned_lifecycle() as scope:
            proc = scope.spawn([sys.executable, "-c", code, str(pids)],
                               start_new_session=True)
            proc.wait(timeout=3)
            local_chrome._stop(proc)
        child = int(pids.read_text())
        assert not alive(child)
    finally:
        clean_pids(pids)


def test_xvfb_startup_without_display_is_bounded(tmp_path, monkeypatch):
    executable = tmp_path / "fake-xvfb"
    pids = tmp_path / "pids"
    executable.write_text(f"""#!{sys.executable}
import os, time
open({str(pids)!r}, 'w').write(str(os.getpid()))
while True: time.sleep(.05)
""")
    executable.chmod(0o755)
    monkeypatch.setenv(local_chrome.XVFB_ENV, str(executable))
    monkeypatch.setattr(local_chrome, "STARTUP_S", .2)
    try:
        started = time.monotonic()
        with pytest.raises(RuntimeError, match="display"):
            with local_chrome.owned_lifecycle(), local_chrome._run_display():
                pytest.fail("silent display accepted")
        assert time.monotonic() - started < 2
        assert not alive(int(pids.read_text()))
    finally:
        clean_pids(pids)


def test_escalation_keeps_lease_until_detached_groups_reaped(tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    chrome = fake_chrome(tmp_path, stubborn=True)
    monkeypatch.setenv(local_chrome.PROFILE_ENV, str(profile))
    monkeypatch.setenv(local_chrome.CHROME_ENV, str(chrome))
    runtime = fake_runtime(tmp_path, """
import local_chrome, signal, time
def main():
    with local_chrome.devtools_endpoint(local_chrome.configured_chrome()):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        time.sleep(30)
""")
    observed = []
    stop = process_lifecycle.ProcessHandle.send_signal

    def inspect_stop(handle, *args, **kwargs):
        # The supervisor must keep the lease even after killing the worker.
        with pytest.raises(ValueError, match="profile already active"):
            with local_chrome.profile_lease(profile):
                pass
        observed.append(handle.pid)
        return stop(handle, *args, **kwargs)

    monkeypatch.setattr(process_lifecycle.ProcessHandle, "send_signal", inspect_stop)
    try:
        with pytest.raises(ValueError, match="timed out"):
            worker().run_worker(runtime, {}, timeout=.6, grace=.15)
        assert observed
        assert not alive(int((profile / "pids").read_text()))
        assert not (profile / "SingletonLock").is_symlink()
    finally:
        clean_pids(profile / "pids")


@pytest.mark.parametrize("entry", ["run", "login"])
def test_cancel_between_spawn_and_return_cleans_before_unlock(tmp_path, monkeypatch, entry):
    profile = tmp_path / "profile"
    chrome = fake_chrome(tmp_path)
    monkeypatch.setenv(local_chrome.PROFILE_ENV, str(profile))
    original = local_chrome._spawn
    started = []

    def interrupted_spawn(*args, **kwargs):
        proc = original(*args, **kwargs)
        started.append(proc.pid)
        # SIGTERM arrives after registration but before caller gets its Popen.
        os.kill(os.getpid(), signal.SIGTERM)
        return proc

    original_close = local_chrome.os.close
    closed_while_alive = []

    def checked_close(fd):
        lease = profile / local_chrome.LEASE_NAME
        is_lease = lease.exists() and os.fstat(fd).st_ino == lease.stat().st_ino
        if is_lease and started and any(alive(pid) for pid in started):
            closed_while_alive.append(fd)
        return original_close(fd)

    monkeypatch.setattr(local_chrome, "_spawn", interrupted_spawn)
    monkeypatch.setattr(local_chrome.os, "close", checked_close)
    try:
        with pytest.raises(SystemExit):
            if entry == "run":
                with local_chrome.devtools_endpoint(str(chrome)):
                    pytest.fail("cancelled startup yielded")
            else:
                local_chrome.login(str(chrome), profile)
        assert not closed_while_alive, "profile lease closed before owned Chrome stopped"
        assert all(not alive(pid) for pid in started)
    finally:
        clean_pids(profile / "pids")


def test_repeated_cancellation_during_teardown_finishes_cleanup(tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    chrome = fake_chrome(tmp_path, stubborn=True)
    monkeypatch.setenv(local_chrome.PROFILE_ENV, str(profile))
    monkeypatch.setattr(local_chrome, "STOP_S", .1)
    real_send = process_lifecycle.ProcessHandle.send_signal
    injected = []

    def signal_during_stop(handle, sig):
        if sig == signal.SIGTERM and not injected:
            injected.append(handle.pid)
            os.kill(os.getpid(), signal.SIGTERM)
            os.kill(os.getpid(), signal.SIGTERM)
        return real_send(handle, sig)

    monkeypatch.setattr(process_lifecycle.ProcessHandle, "send_signal", signal_during_stop)
    with pytest.raises(SystemExit):
        with local_chrome.devtools_endpoint(str(chrome)):
            pid = int((profile / "pids").read_text())
    assert injected
    assert not alive(pid)
    assert not (profile / "SingletonLock").is_symlink()


def test_cancel_during_partial_xvfb_startup_reaps_display(tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    pids = tmp_path / "display-pids"
    xvfb = tmp_path / "fake-xvfb"
    xvfb.write_text(f"""#!{sys.executable}
import os, signal, sys, time
open({str(pids)!r}, 'w').write(str(os.getpid()))
signal.signal(signal.SIGTERM, signal.SIG_IGN)
fd = int(sys.argv[sys.argv.index('-displayfd') + 1])
os.write(fd, b'8')
while True: time.sleep(.05)
""")
    xvfb.chmod(0o755)
    monkeypatch.setenv(local_chrome.PROFILE_ENV, str(profile))
    monkeypatch.setenv(local_chrome.CHROME_ENV, str(tmp_path / "never-started"))
    monkeypatch.setenv(local_chrome.XVFB_ENV, str(xvfb))
    runtime = fake_runtime(tmp_path, """
import local_chrome
def main():
    local_chrome.STOP_S = .1
    with local_chrome.devtools_endpoint(local_chrome.configured_chrome()):
        raise AssertionError("incomplete display must not yield")
""")
    try:
        with pytest.raises(ValueError, match="timed out"):
            worker().run_worker(runtime, {}, timeout=.5, grace=.5)
        assert not alive(int(pids.read_text()))
        with local_chrome.profile_lease(profile):
            pass
    finally:
        clean_pids(pids)


def test_partial_display_number_never_admits_startup(tmp_path, monkeypatch):
    executable = tmp_path / "fake-xvfb"
    executable.write_text(f"""#!{sys.executable}
import os, sys, time
os.write(int(sys.argv[sys.argv.index('-displayfd') + 1]), b'8')
while True: time.sleep(.05)
""")
    executable.chmod(0o755)
    monkeypatch.setenv(local_chrome.XVFB_ENV, str(executable))
    monkeypatch.setattr(local_chrome, "STARTUP_S", .15)
    with local_chrome.owned_lifecycle():
        with pytest.raises(RuntimeError, match="display"):
            with local_chrome._run_display():
                pytest.fail("partial display number admitted")


def test_cancellation_at_display_pipe_close_does_not_double_close(tmp_path, monkeypatch):
    executable = tmp_path / "fake-xvfb"
    executable.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(30)\n")
    executable.chmod(0o755)
    monkeypatch.setenv(local_chrome.XVFB_ENV, str(executable))
    real_close = os.close
    real_spawn = local_chrome._spawn
    started = []
    cancelled = []

    def record_spawn(*args, **kwargs):
        proc = real_spawn(*args, **kwargs)
        started.append(proc.pid)
        return proc

    def close_then_cancel(fd):
        real_close(fd)
        if started and not cancelled:
            cancelled.extend(started)
            os.kill(os.getpid(), signal.SIGTERM)

    monkeypatch.setattr(local_chrome, "_spawn", record_spawn)
    monkeypatch.setattr(local_chrome.os, "close", close_then_cancel)
    with pytest.raises(SystemExit):
        with local_chrome.owned_lifecycle(), local_chrome._run_display():
            pytest.fail("cancelled display yielded")
    assert cancelled
    assert all(not alive(pid) for pid in cancelled)


def test_lease_contention_before_chrome_creates_singleton(tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    chrome = fake_chrome(tmp_path)
    monkeypatch.setenv(local_chrome.PROFILE_ENV, str(profile))
    with local_chrome.profile_lease(profile):
        assert not (profile / "SingletonLock").exists()
        for action in (
            "with local_chrome.devtools_endpoint(sys.argv[1]): pass",
            "local_chrome.login(sys.argv[1], pathlib.Path(sys.argv[2]))",
        ):
            proc = subprocess.run(
                [sys.executable, "-c", "import local_chrome, pathlib, sys\n" + action,
                 str(chrome), str(profile)],
                env={**os.environ, "PYTHONPATH": str(SCRIPTS)},
                capture_output=True, timeout=3,
            )
            assert proc.returncode != 0
            assert b"profile already active" in proc.stderr
        assert not (profile / "pids").exists()


def test_sigterm_supervisor_reaps_worker_browser_and_display(tmp_path):
    profile = tmp_path / "profile"
    chrome = fake_chrome(tmp_path, stubborn=True)
    display_pids = tmp_path / "display-pids"
    xvfb = tmp_path / "fake-xvfb"
    xvfb.write_text(f"""#!{sys.executable}
import os, signal, sys, time
open({str(display_pids)!r}, 'w').write(str(os.getpid()))
signal.signal(signal.SIGTERM, signal.SIG_IGN)
os.write(int(sys.argv[sys.argv.index('-displayfd') + 1]), b'82\\n')
while True: time.sleep(.05)
""")
    xvfb.chmod(0o755)
    runtime = fake_runtime(tmp_path, """
import local_chrome, time
def main():
    local_chrome.STOP_S = .1
    with local_chrome.devtools_endpoint(local_chrome.configured_chrome()):
        time.sleep(30)
""")
    env = {**os.environ, "PYTHONPATH": str(SCRIPTS),
           local_chrome.CHROME_ENV: str(chrome), local_chrome.PROFILE_ENV: str(profile),
           local_chrome.XVFB_ENV: str(xvfb)}
    proc = subprocess.Popen(
        [sys.executable, "-c",
         "from pathlib import Path; from exact_worker import run_worker; import sys; "
         "run_worker(Path(sys.argv[1]), {}, timeout=20, grace=1)", str(runtime)],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 3
        while not (profile / "pids").exists() and time.monotonic() < deadline:
            time.sleep(.01)
        assert (profile / "pids").exists()
        proc.terminate()
        stdout, stderr = proc.communicate(timeout=4)
        assert proc.returncode == 128 + signal.SIGTERM, stderr
        assert not alive(int((profile / "pids").read_text()))
        assert not alive(int(display_pids.read_text()))
        assert not (profile / "SingletonLock").is_symlink()
        with local_chrome.profile_lease(profile):
            pass
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        clean_pids(profile / "pids")
        clean_pids(display_pids)
