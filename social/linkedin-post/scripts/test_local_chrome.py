"""A Chrome left on the kept profile by a killed run is ended; the user's login window is not.

A sleeping Python process with Chrome's switches on its command line stands in for Chrome.
Run: python3 -m pytest social/linkedin-post/scripts/test_local_chrome.py
"""
import subprocess
import sys
import time

import pytest

import local_chrome


def _fake_chrome(profile, *switches):
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)",
                                f"--user-data-dir={profile}", *switches], start_new_session=True)
    (profile / "SingletonLock").symlink_to(f"thishost-{process.pid}")
    return process


@pytest.fixture
def started(monkeypatch):
    # The stand-in stays a zombie until this test reaps it, so it looks alive for all of STOP_S.
    # A real leftover's parent is dead and init reaps it at once.
    monkeypatch.setattr(local_chrome, "STOP_S", 1)
    processes = []
    yield processes
    for process in processes:
        process.kill()
        process.wait()


def test_a_run_left_on_the_profile_is_ended(tmp_path, started):
    leftover = _fake_chrome(tmp_path, local_chrome.RUN_MARKER)
    started.append(leftover)
    local_chrome.end_leftover_run(tmp_path)
    assert leftover.wait(timeout=5) is not None


def test_the_login_window_is_left_open(tmp_path, started):
    login_window = _fake_chrome(tmp_path)
    started.append(login_window)
    local_chrome.end_leftover_run(tmp_path)
    time.sleep(0.3)
    assert login_window.poll() is None


def test_a_profile_without_a_lock_is_left_alone(tmp_path):
    local_chrome.end_leftover_run(tmp_path)
