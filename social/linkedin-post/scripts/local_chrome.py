"""Run the poster's browser on this machine instead of on browserless.

LinkedIn signs a session out when its cookie shows up from a second network address: the
cookie comes from the user's browser at home, and browserless runs elsewhere. A local Chrome
uses the home address. Set LINKEDIN_LOCAL_CHROME to the Chrome executable to use it.

Each run gets a fresh, temporary profile, so nothing from the user's own browser profile is
read or changed. The profile and the browser are removed when the run ends.
"""
import contextlib
import os
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

CHROME_ENV = "LINKEDIN_LOCAL_CHROME"
# The pipeline converts each slot to this zone (--account-tz) before the poster types it, and
# browserless ran in it. Keep the same zone so a typed time means the same instant.
TIMEZONE_ENV = "LINKEDIN_BROWSER_TZ"
DEFAULT_TIMEZONE = "America/Los_Angeles"
STARTUP_S = 30
STOP_S = 10


def configured_chrome() -> str | None:
    """The Chrome executable named by $LINKEDIN_LOCAL_CHROME, or None to use browserless."""
    return os.environ.get(CHROME_ENV) or None


@contextlib.contextmanager
def devtools_endpoint(executable: str):
    """Start Chrome headless with a temporary profile; yield its DevTools WebSocket URL.
    Raises RuntimeError when Chrome does not report one within STARTUP_S seconds."""
    profile = Path(tempfile.mkdtemp(prefix="li-chrome-"))
    timezone = os.environ.get(TIMEZONE_ENV, DEFAULT_TIMEZONE)
    browser = subprocess.Popen(
        [executable, "--headless=new", "--remote-debugging-port=0", f"--user-data-dir={profile}",
         "--no-first-run", "--no-default-browser-check", "--window-size=1300,1300", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        env={**os.environ, "TZ": timezone})
    try:
        yield _endpoint(profile, browser)
    finally:
        _stop(browser)
        shutil.rmtree(profile, ignore_errors=True)


def _endpoint(profile: Path, browser: subprocess.Popen) -> str:
    """Chrome writes its port and browser path to DevToolsActivePort once it listens."""
    port_file = profile / "DevToolsActivePort"
    deadline = time.monotonic() + STARTUP_S
    while time.monotonic() < deadline:
        if browser.poll() is not None:
            raise RuntimeError(f"local Chrome exited with code {browser.returncode} before it listened")
        lines = port_file.read_text().split() if port_file.is_file() else []
        if len(lines) == 2:
            return f"ws://127.0.0.1:{lines[0]}{lines[1]}"
        time.sleep(0.2)
    raise RuntimeError(f"local Chrome reported no DevTools port within {STARTUP_S}s")


def _stop(browser: subprocess.Popen) -> None:
    """End Chrome and every process it started (its renderers share its process group)."""
    with contextlib.suppress(ProcessLookupError):
        os.killpg(browser.pid, signal.SIGTERM)
    try:
        browser.wait(timeout=STOP_S)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(browser.pid, signal.SIGKILL)
        browser.wait()
