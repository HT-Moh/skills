"""Run the poster's browser on this machine, with a LinkedIn login of its own.

A copy of the user's login cookies in a second browser makes LinkedIn end that login
everywhere, the user's own browser included: the same cookie shows up on two devices.
So the poster keeps its own Chrome profile, in which the user logs in once:

    python3 local_chrome.py login      # opens Chrome; log in to LinkedIn, then close it

LinkedIn then knows two devices with a login each. Every run starts Chrome on that profile
with the login LinkedIn itself keeps up to date, and loads no exported cookies.

LINKEDIN_LOCAL_CHROME names the Chrome executable; LINKEDIN_CHROME_PROFILE names the kept
profile folder. LINKEDIN_XVFB names Xvfb: each run's window then opens on a private virtual
display, not on the user's desktop, and a run needs no desktop session at all. With no profile set, each run gets a temporary profile and the exported
cookies, as before.
"""
import contextlib
import os
import select
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from process_lifecycle import ProcessScope, current_scope, defer_cancellation
from profile_lease import LEASE_NAME, ProfileLease

CHROME_ENV = "LINKEDIN_LOCAL_CHROME"
PROFILE_ENV = "LINKEDIN_CHROME_PROFILE"
XVFB_ENV = "LINKEDIN_XVFB"
# The size of the desktop the user logs in on, so a run's page sees the screen it saw then.
XVFB_SCREEN = "2560x1440x24"
# The pipeline converts each slot to this zone (--account-tz) before the poster types it, and
# browserless ran in it. Keep the same zone so a typed time means the same instant.
TIMEZONE_ENV = "LINKEDIN_BROWSER_TZ"
DEFAULT_TIMEZONE = "America/Los_Angeles"
LOGIN_URL = "https://www.linkedin.com/login"
STARTUP_S = 30
STOP_S = 10
# Only a run starts Chrome with this switch. It identifies a run, but does not
# establish that its owner is dead or grant another process permission to kill it.
RUN_MARKER = "--remote-debugging-port=0"
# The login window and every run use the same switches, so the profile's cookie store is
# read the way it was written: "basic" keeps the encryption key out of the desktop keyring,
# which a run started without a desktop session cannot reach.
COMMON_SWITCHES = ["--no-first-run", "--no-default-browser-check", "--password-store=basic"]
# A run uses a real (not headless) window: a headless browser differs from the one the user
# logged in with. A window nobody looks at must keep rendering at full speed.
RUN_SWITCHES = ["--window-size=1300,1300",
                "--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding",
                "--disable-background-timer-throttling",
                # A DevTools connection sets navigator.webdriver=true, which a person's browser
                # never reports. This switch keeps it false.
                "--disable-blink-features=AutomationControlled"]


def owned_lifecycle():
    """Compatibility entrypoint; process ownership lives in process_lifecycle."""
    return ProcessScope(grace=STOP_S)


@contextlib.contextmanager
def profile_lease(profile: Path):
    with ProfileLease(profile) as lease:
        yield lease.fd


def _refuse_active_profile(profile):
    try:
        target = os.readlink(profile / "SingletonLock")
        pid = int(target.rsplit("-", 1)[1])
    except FileNotFoundError:
        return
    except (OSError, ValueError, IndexError) as exc:
        raise ValueError("publisher profile already active (unknown lock)") from exc
    if pid <= 0 or _alive(pid):
        raise ValueError("publisher profile already active")


def _spawn(*args, profile=None, **kwargs):
    return current_scope().spawn(*args, start_new_session=True, **kwargs)


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
    profile = (kept or Path(tempfile.mkdtemp(prefix="li-chrome-"))).resolve()
    completed = False
    try:
        with ProfileLease(profile) as lease:
            scope = owned_lifecycle()
            try:
                with scope:
                    _refuse_active_profile(profile)
                    (profile / "DevToolsActivePort").unlink(missing_ok=True)
                    with _run_display() as display:
                        browser = _start(executable, profile, [*RUN_SWITCHES, RUN_MARKER, "about:blank"], display)
                        yield _endpoint(profile, browser)
            finally:
                if not scope.errors:
                    lease.clean_singleton(scope.identities)
                    completed = True
    finally:
        if kept is None and completed:
            shutil.rmtree(profile, ignore_errors=True)


def login(executable: str, profile: Path) -> None:
    """Open a visible Chrome on `profile` at LinkedIn's login page; return once it is closed."""
    profile = profile.resolve()
    with ProfileLease(profile) as lease:
        scope = owned_lifecycle()
        try:
            with scope:
                _refuse_active_profile(profile)
                print(f"Log in to LinkedIn in the Chrome window, then close the window. Profile: {profile}")
                browser = _start(executable, profile, ["--window-size=1300,1000", LOGIN_URL], {})
                browser.wait()
        finally:
            if not scope.errors:
                lease.clean_singleton(scope.identities)


def end_leftover_run(profile: Path) -> None:
    """Compatibility check, never kill an unowned browser based on its switches.

    RUN_MARKER proves what a process does, not that its owner died. Recovery of a
    genuinely orphaned browser now requires explicit operator action.
    """
    with profile_lease(profile):
        _refuse_active_profile(profile)


@contextlib.contextmanager
def _run_display():
    """The environment that places a run's window: a private Xvfb display while $LINKEDIN_XVFB
    names Xvfb, else none, and the window opens on the user's desktop. Xvfb picks a free
    display number and writes it to the -displayfd pipe once it accepts connections."""
    xvfb = os.environ.get(XVFB_ENV)
    if not xvfb:
        yield {}
        return
    read_end = write_end = server = None
    try:
        with defer_cancellation():
            read_end, write_end = os.pipe()
            server = _spawn([xvfb, "-displayfd", str(write_end), "-screen", "0", XVFB_SCREEN,
                             "-nolisten", "tcp"], pass_fds=(write_end,), stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
            os.close(write_end)
            write_end = None
        deadline = time.monotonic() + STARTUP_S
        number = b""
        while b"\n" not in number and time.monotonic() < deadline:
            ready, _, _ = select.select([read_end], [], [], max(0, deadline - time.monotonic()))
            if not ready:
                break
            data = os.read(read_end, 32)
            if not data:
                break
            number += data
            if len(number) > 16:
                break
        if not number.endswith(b"\n") or not number[:-1].isdigit() or len(number) > 7:
            raise RuntimeError("Xvfb did not report a valid display before startup deadline")
        yield {"DISPLAY": f":{number[:-1].decode('ascii')}"}
    finally:
        with defer_cancellation(cleanup=True):
            try:
                if server is not None:
                    _stop(server)
            finally:
                if read_end is not None:
                    os.close(read_end)
                if write_end is not None:
                    os.close(write_end)


def _start(executable: str, profile: Path, switches: list[str], display: dict) -> subprocess.Popen:
    timezone = os.environ.get(TIMEZONE_ENV, DEFAULT_TIMEZONE)
    return _spawn([executable, f"--user-data-dir={profile}", *COMMON_SWITCHES, *switches],
                  profile=profile, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                  env={**os.environ, "TZ": timezone, **display})


def _endpoint(profile: Path, browser: subprocess.Popen) -> str:
    """Chrome writes its port and browser path to DevToolsActivePort once it listens."""
    port_file = profile / "DevToolsActivePort"
    deadline = time.monotonic() + STARTUP_S
    while time.monotonic() < deadline:
        current_scope().refresh()
        if browser.poll() is not None:
            raise RuntimeError(f"local Chrome exited with code {browser.returncode} before it listened "
                               f"(is a Chrome window still open on {profile}?)")
        lines = port_file.read_text().split() if port_file.is_file() else []
        if len(lines) == 2:
            return f"ws://127.0.0.1:{lines[0]}{lines[1]}"
        time.sleep(0.2)
    raise RuntimeError(f"local Chrome reported no DevTools port within {STARTUP_S}s")


def _stop(browser: subprocess.Popen) -> None:
    """Compatibility helper: teardown belongs to the complete synchronous scope."""
    current_scope().stop()


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


if __name__ == "__main__":
    chrome, profile = configured_chrome(), kept_profile()
    if sys.argv[1:] != ["login"] or not chrome or not profile:
        sys.exit(f"usage: {CHROME_ENV}=<chrome> {PROFILE_ENV}=<folder> python3 local_chrome.py login")
    login(chrome, profile)
