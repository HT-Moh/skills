"""QUALITY regressions: authoritative typed failures and invocation-owned cancellation."""
import json
import os
import signal
import sys
import time

import pytest

from test_capture_control import SCRIPTS
import process_lifecycle as life
from capture_control import CleanupContext
from exact_capture_clock import Deadline
from profile_lease import ProfileLease


def scope():
    return life.ProcessScope(use_cgroup=False,
        capture_deadline=Deadline(str(time.monotonic_ns() + 60_000_000_000)))


def failing_close(monkeypatch, handle, message):
    close = handle.close
    def fail():
        close()  # Actual owned pidfd/proc directory closes before injected diagnostic.
        raise OSError(message)
    monkeypatch.setattr(handle, "close", fail)


@pytest.mark.parametrize("kind", ["cleanup", "exit", "keyboard"])
def test_nested_cleanup_aggregate_keeps_primary_identity_and_every_owner(monkeypatch, kind):
    primary = {"cleanup": life.CleanupError(["first entered owner failed"]),
               "exit": SystemExit(143), "keyboard": KeyboardInterrupt()}[kind]
    if kind != "cleanup":
        life.retain_cleanup_failure(primary, life.CleanupError(["first entered owner failed"]))
    before = set(os.listdir("/proc/self/fd"))
    with pytest.raises(type(primary)) as caught:
        with scope() as root:
            failing_close(monkeypatch, root.root, "root proc-handle close failed")
            with life.ProcessScope(use_cgroup=False) as middle:
                failing_close(monkeypatch, middle.root, "middle proc-handle close failed")
                with life.ProcessScope(use_cgroup=False) as inner:
                    failing_close(monkeypatch, inner.root, "inner proc-handle close failed")
                    raise primary
    assert caught.value is primary
    expected = {"first entered owner failed", "root proc-handle close failed",
                "middle proc-handle close failed", "inner proc-handle close failed"}
    assert expected <= set(life.cleanup_failure(primary).errors)
    life.retain_cleanup_failure(primary, life.CleanupError(["inner proc-handle close failed", "last owner failed"]))
    life.retain_cleanup_failure(primary, life.CleanupError(["last owner failed"]))
    aggregate = life.cleanup_failure(primary)
    assert expected | {"last owner failed"} <= set(aggregate.errors)
    assert aggregate.errors.count("last owner failed") == 1
    assert aggregate.errors.count("inner proc-handle close failed") == 1
    if kind == "cleanup":
        assert primary.errors == aggregate.errors
        assert all(message in str(primary) for message in expected | {"last owner failed"})
    elif kind == "exit":
        assert primary.code == 143 and str(primary) == "143"
    assert set(os.listdir("/proc/self/fd")) == before


def test_retained_lease_control_failure_is_visible_in_original_typed_error(tmp_path, monkeypatch):
    primary = life.CleanupError(["first entered owner failed"])
    with pytest.raises(life.CleanupError) as caught:
        with scope() as root:
            close = root.capture_context.close
            def fail():
                close()
                raise OSError("final control-close fault")
            monkeypatch.setattr(root.capture_context, "close", fail)
            with ProfileLease(tmp_path / "profile"):
                raise primary
    assert caught.value is primary
    aggregate = life.cleanup_failure(primary)
    for message in ("first entered owner failed", "final control-close fault"):
        assert message in aggregate.errors and message in str(primary)
    marker = json.loads((tmp_path / "profile/.linkedin-poster.lease").read_text())
    assert marker["quarantined"] and "final control-close fault" in marker["reason"]
    assert aggregate.errors == list(primary._publisher_cleanup.errors) == primary.errors


def independent_preflights():
    """Real available input and a separate successful capture relay, before a root reset."""
    from process_output import read_initial, run_stream
    from test_capture_exchange import envelope, wire, terminal
    read, write = os.pipe()
    output_read, output_write = os.pipe()
    try:
        os.write(write, b'{"fresh":true}\n')
        assert read_initial(read, timeout=.2) == b'{"fresh":true}\n'
        value = envelope()
        output = wire(terminal(value, "refused_before_submit"))
        driver = "import sys;sys.stdin.buffer.readline();sys.stdout.buffer.write(" + repr(output) + ");sys.stdout.flush()"
        result = run_stream([sys.executable, "-c", driver], input=wire(value),
            upstream=read, downstream=output_write, frame=lambda _: "terminal",
            acknowledgment=lambda _: None, timeout=2,
            capture_deadline=Deadline(value["expires_at_monotonic_ns"]))
        assert result.exit_code == 0
        assert os.read(output_read, len(output) + 1) == output
    finally:
        os.close(read)
        os.close(write)
        os.close(output_read)
        os.close(output_write)


@pytest.mark.parametrize("fault", ["none", "control", "restore", "release"])
def test_sigterm_during_real_memfd_entry_clears_only_own_latch(monkeypatch, fault):
    handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    before = set(os.listdir("/proc/self/fd"))
    captured = []
    original_memfd, original_signal = os.memfd_create, signal.signal
    root = scope()
    close = CleanupContext.close
    def created(*args):
        fd = original_memfd(*args)
        os.kill(os.getpid(), signal.SIGTERM)
        captured.append((fd, life._cancelled))
        return fd
    def close_fault(ctx):
        close(ctx)
        if fault == "control":
            raise OSError("partial entry control-close fault")
    def restore(sig, handler):
        result = original_signal(sig, handler)
        if fault == "restore" and sig == signal.SIGTERM and handler == handlers[sig]:
            raise OSError("partial entry handler-restoration fault")
        return result
    release = root._release
    def release_fault(value=None):
        release(value)
        if fault == "release":
            raise OSError("partial entry release fault")
    try:
        with monkeypatch.context() as patch:
            patch.setattr(os, "memfd_create", created)
            patch.setattr(CleanupContext, "close", close_fault)
            patch.setattr(signal, "signal", restore)
            patch.setattr(root, "_release", release_fault)
            with pytest.raises(SystemExit) as caught:
                with root:
                    pytest.fail("cancelled entry reached body")
        assert caught.value is captured[0][1] and caught.value.code == 143
        assert not life._scopes and life._entering_capture is None
        assert root.capture_context.fd is None
        assert {sig: signal.getsignal(sig) for sig in handlers} == handlers
        if fault != "none":
            assert "partial entry" in str(life.cleanup_failure(caught.value))
            assert isinstance(caught.value.__cause__, life.CleanupError)
        # Exercise preflights before inspecting the latch; no next-root reset can hide it.
        independent_preflights()
        assert life._cancelled is None and life._cancelled_at is None
        assert set(os.listdir("/proc/self/fd")) == before
    finally:
        # Isolate the deliberately red stale-global regression from later tests.
        life._cancelled = life._cancelled_at = life._entering_capture = None
        for sig, handler in handlers.items():
            original_signal(sig, handler)


def test_nested_failed_entry_preserves_outer_signal_and_entering_owner(monkeypatch):
    root = scope()
    ensure = root._ensure_context
    primary = []
    entry_error = RuntimeError("nested entry failed")
    def nested_during_entry():
        ensure()
        os.kill(os.getpid(), signal.SIGTERM)
        primary.append(life._cancelled)
        nested = life.ProcessScope(use_cgroup=False)
        def fail():
            raise entry_error
        monkeypatch.setattr(nested, "_ensure_context", fail)
        with pytest.raises(SystemExit) as caught:
            with nested:
                pytest.fail("nested entry reached body")
        assert caught.value is primary[0]
        assert life._cancelled is primary[0]
        assert life._cancelled_at is not None
        assert life._entering_capture is root
        assert "nested entry failed" in str(life.cleanup_failure(primary[0]))
    monkeypatch.setattr(root, "_ensure_context", nested_during_entry)
    try:
        with pytest.raises(SystemExit) as caught:
            with root:
                pytest.fail("outer entry reached body")
        assert caught.value is primary[0] and caught.value.code == 143
        assert root.capture_context.fd is None
        assert life._cancelled is None and life._entering_capture is None
        independent_preflights()
    finally:
        life._cancelled = life._cancelled_at = life._entering_capture = None


def test_first_signal_during_failed_entry_release_retains_original_evidence(monkeypatch):
    root = scope()
    original = RuntimeError("entry acquisition failed")
    close = CleanupContext.close
    captured = []
    def fail_create(*args):
        raise original
    def cancelled_close(ctx):
        os.kill(os.getpid(), signal.SIGTERM)
        captured.append(life._cancelled)
        close(ctx)
        raise OSError("release control-close failed")
    monkeypatch.setattr(life.OwnedCgroup, "create", fail_create)
    monkeypatch.setattr(CleanupContext, "close", cancelled_close)
    root.use_cgroup = True
    try:
        with pytest.raises(SystemExit) as caught:
            with root:
                pytest.fail("failed entry reached body")
        assert caught.value is captured[0]
        assert "entry acquisition failed" in str(life.cleanup_failure(caught.value))
        assert "release control-close failed" in str(life.cleanup_failure(caught.value))
        assert life._cancelled is None and life._cancelled_at is None
        assert not life._scopes and root.capture_context.fd is None
    finally:
        life._cancelled = life._cancelled_at = life._entering_capture = None


def test_nested_failed_entry_leaves_entered_outer_cancellation_owned(monkeypatch):
    captured = []
    with pytest.raises(SystemExit) as caught:
        with scope() as root:
            nested = life.ProcessScope(use_cgroup=False)
            def fail():
                os.kill(os.getpid(), signal.SIGTERM)
                captured.append(life._cancelled)
                raise OSError("nested acquisition failed")
            monkeypatch.setattr(nested, "_ensure_context", fail)
            with pytest.raises(SystemExit) as inner:
                with nested:
                    pytest.fail("nested body reached")
            assert inner.value is captured[0]
            assert life._scopes == [root] and life._cancelled is captured[0]
            assert root.capture_context.fd is not None and life._cancelled_at is not None
    assert caught.value is captured[0]
    assert "nested acquisition failed" in str(life.cleanup_failure(caught.value))
    assert life._cancelled is None and not life._scopes
    independent_preflights()


def test_root_exit_release_fault_finalizes_cancellation_like_failed_entry(monkeypatch):
    root = scope()
    release = root._release
    captured = []
    handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    def fail(value=None):
        os.kill(os.getpid(), signal.SIGTERM)
        captured.append(life._cancelled)
        release(value)
        raise OSError("final root release fault")
    monkeypatch.setattr(root, "_release", fail)
    with pytest.raises(SystemExit) as caught:
        with root:
            pass
    assert caught.value is captured[0] and caught.value.code == 143
    assert "final root release fault" in str(life.cleanup_failure(caught.value))
    assert not life._scopes and life._cancelled is None and life._cancelled_at is None
    assert root.capture_context.fd is None
    assert {sig: signal.getsignal(sig) for sig in handlers} == handlers
    independent_preflights()


def test_untyped_cause_and_context_are_not_cleanup_authority():
    primary = RuntimeError("work failed")
    primary.__cause__ = life.CleanupError(["untrusted cause"])
    primary.__context__ = life.CleanupError(["untrusted context"])
    assert life.cleanup_failure(primary) is None
    life.retain_cleanup_failure(primary, life.CleanupError(["explicit typed owner"]))
    assert life.cleanup_failure(primary).errors == ["explicit typed owner"]
    assert str(primary) == "work failed"
