"""Reviewed same-host monotonic contract, separate from legacy runtime identity."""
import time
import os
import sys
import shutil

from exact_capture import decimal, fields

SUPPORTED = dict(platform="linux", architecture="x64", node_version="v26.2.0", libuv_version="1.52.1")


def compatibility(value: dict) -> None:
    fields(value, set(SUPPORTED) | {"time_namespace_id"})
    decimal(value["time_namespace_id"])
    if any(value[key] != expected for key, expected in SUPPORTED.items()):
        raise ValueError("unsupported capture clock compatibility")


def observe_compatibility(deadline=None) -> dict:
    """Observe actual Node/libuv and inherited namespace, never infer versions."""
    from process_output import run_bounded
    node = shutil.which("node")
    if not node or sys.platform != "linux":
        raise ValueError("capture clock unavailable")
    probe = (
        "console.log(JSON.stringify({platform:process.platform,architecture:process.arch,"
        "node_version:process.version,libuv_version:process.versions.uv,"
        "time_namespace_id:require('node:fs').statSync('/proc/self/ns/time',"
        "{bigint:true}).ino.toString()}))"
    )
    result = run_bounded([node, "-e", probe], input="", timeout=5, capture_deadline=deadline,
                         auxiliary=True)
    from exact_capture import decode_capture
    value = decode_capture(result.stdout.encode("utf-8"))
    if result.returncode or result.stderr:
        raise ValueError("capture compatibility probe failed")
    compatibility(value)
    if value["time_namespace_id"] != str(os.stat("/proc/self/ns/time").st_ino):
        raise ValueError("capture time namespace changed")
    return value


def verify_compatibility(expected: dict, deadline=None) -> None:
    compatibility(expected)
    if observe_compatibility(deadline) != expected:
        raise ValueError("capture compatibility changed")


class Deadline:
    """Transport one unchanged expiry; convert only bounded remaining durations."""

    def __init__(self, expiry: str):
        self.expiry = decimal(expiry)
        now = time.clock_gettime_ns(time.CLOCK_MONOTONIC)
        if not 15_000_000_000 < self.expiry - now <= 300_000_000_000:
            raise ValueError("expired or excessive capture deadline")

    def remaining(self, reserve: int = 15) -> float:
        from process_lifecycle import current_scope, cancellation_checkpoint
        cancellation_checkpoint()
        remaining = self.expiry - reserve * 1_000_000_000 - time.clock_gettime_ns(time.CLOCK_MONOTONIC)
        if reserve == 15:
            try:
                scope = current_scope()
            except RuntimeError:
                scope = None
            if scope is not None and scope.capture_context is not None:
                remaining = min(remaining, int(scope.check_work() * 1_000_000_000))
        if remaining <= 0:
            raise ValueError("capture deadline expired")
        return remaining / 1_000_000_000
