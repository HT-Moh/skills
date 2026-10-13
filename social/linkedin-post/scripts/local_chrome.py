"""Run the poster's browser on this machine, with a LinkedIn login of its own.

A copy of the user's login cookies in a second browser makes LinkedIn end that login
everywhere, the user's own browser included: the same cookie shows up on two devices.
So the poster keeps its own Chrome profile, in which the user logs in once:

    python3 local_chrome.py login      # opens Chrome; log in to LinkedIn, then close it

LinkedIn then knows two devices with a login each. Every run starts Chrome on that profile
with the login LinkedIn itself keeps up to date, and loads no exported cookies.

LINKEDIN_LOCAL_CHROME names the Chrome executable; LINKEDIN_CHROME_PROFILE names the kept
profile folder. With no profile set, each run gets a temporary profile and the exported
cookies, as before.
"""
import contextlib
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CHROME_ENV = "LINKEDIN_LOCAL_CHROME"
PROFILE_ENV = "LINKEDIN_CHROME_PROFILE"
# The pipeline converts each slot to this zone (--account-tz) before the poster types it, and
# browserless ran in it. Keep the same zone so a typed time means the same instant.
TIMEZONE_ENV = "LINKEDIN_BROWSER_TZ"
DEFAULT_TIMEZONE = "America/Los_Angeles"
LOGIN_URL = "https://www.linkedin.com/login"
STARTUP_S = 30
STOP_S = 10
# The login window and every run use the same switches, so the profile's cookie store is
# read the way it was written: "basic" keeps the encryption key out of the desktop keyring,
# which a run started without a desktop session cannot reach.
COMMON_SWITCHES = ["--no-first-run", "--no-default-browser-check", "--password-store=basic"]
# A run uses a real (not headless) window, placed off screen: a headless browser differs from
# the one the user logged in with. Hidden windows must keep rendering at full speed.
RUN_SWITCHES = ["--window-position=-3000,-3000", "--window-size=1300,1300",
                "--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding",
                "--disable-background-timer-throttling",
                # A DevTools connection sets navigator.webdriver=true, which a person's browser
                # never reports. This switch keeps it false.
                "--disable-blink-features=AutomationControlled"]


def configured_chrome() -> str | None:
    """The Chrome executable named by $LINKEDIN_LOCAL_CHROME, or None to use browserless."""
    return os.environ.get(CHROME_ENV) or None


def kept_profile() -> Path | None:
    """The profile folder named by $LINKEDIN_CHROME_PROFILE, or None for a temporary one."""
    named = os.environ.get(PROFILE_ENV)
    return Path(named).expanduser() if named else None


@contextlib.contextmanager
def devtools_endpoint(executable: str):
    """Start Chrome on the kept profile (or a temporary one); yield its DevTools WebSocket
    URL. Raises RuntimeError when Chrome does not report one within STARTUP_S seconds."""
    kept = kept_profile()
    profile = kept or Path(tempfile.mkdtemp(prefix="li-chrome-"))
    (profile / "DevToolsActivePort").unlink(missing_ok=True)
    browser = _start(executable, profile, [*RUN_SWITCHES, "--remote-debugging-port=0", "about:blank"])
    try:
        yield _endpoint(profile, browser)
    finally:
        _stop(browser)
        if kept is None:
            shutil.rmtree(profile, ignore_errors=True)


def login(executable: str, profile: Path) -> None:
    """Open a visible Chrome on `profile` at LinkedIn's login page; return once it is closed."""
    profile.mkdir(parents=True, exist_ok=True)
    print(f"Log in to LinkedIn in the Chrome window, then close the window. Profile: {profile}")
    _start(executable, profile, ["--window-size=1300,1000", LOGIN_URL]).wait()


def _start(executable: str, profile: Path, switches: list[str]) -> subprocess.Popen:
    timezone = os.environ.get(TIMEZONE_ENV, DEFAULT_TIMEZONE)
    return subprocess.Popen([executable, f"--user-data-dir={profile}", *COMMON_SWITCHES, *switches],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
                            env={**os.environ, "TZ": timezone})


def _endpoint(profile: Path, browser: subprocess.Popen) -> str:
    """Chrome writes its port and browser path to DevToolsActivePort once it listens."""
    port_file = profile / "DevToolsActivePort"
    deadline = time.monotonic() + STARTUP_S
    while time.monotonic() < deadline:
        if browser.poll() is not None:
            raise RuntimeError(f"local Chrome exited with code {browser.returncode} before it listened "
                               f"(is a Chrome window still open on {profile}?)")
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


if __name__ == "__main__":
    chrome, profile = configured_chrome(), kept_profile()
    if sys.argv[1:] != ["login"] or not chrome or not profile:
        sys.exit(f"usage: {CHROME_ENV}=<chrome> {PROFILE_ENV}=<folder> python3 local_chrome.py login")
    login(chrome, profile)
