"""The risk floor an item's ops demand, and the effective risk that results. Standard library only."""
import os

from plan_schema import REVIEW_OP_KINDS, SENSITIVE_BASENAMES, SENSITIVE_JSON_ROOTS, SENSITIVE_PATH_SEGMENTS, json_root


def _op_floor(op: dict) -> str:
    """The lowest risk an op may carry, from what it touches."""
    kind = op.get("kind")
    if kind == "manual":
        return "safe"
    if kind in REVIEW_OP_KINDS:
        return "review"
    if kind.startswith("json_") and json_root(op) in SENSITIVE_JSON_ROOTS:
        return "review"
    target = os.path.expanduser(str(op.get("file") or op.get("link") or ""))
    base = os.path.basename(target)
    if any(seg in target for seg in SENSITIVE_PATH_SEGMENTS) or base in SENSITIVE_BASENAMES:
        return "review"
    if kind.startswith("file_") and (base.startswith("settings") and base.endswith(".json") or base == ".mcp.json"):
        return "review"  # whole-file edits of settings or MCP files; json ops are judged by their path
    if kind == "file_create" and isinstance(op.get("mode"), int) and op["mode"] & 0o111:
        return "review"  # an executable file
    return "safe"


def effective_risk(item: dict) -> str:
    """Declared risk raised to the floor the ops and reversibility demand."""
    declared = item.get("risk", "review")
    if declared == "manual":
        return "manual"
    floors = [_op_floor(op) for op in item.get("ops") or [] if isinstance(op, dict)]
    if item.get("reversible", "full") != "full":
        floors.append("review")
    return "review" if declared == "review" or "review" in floors else "safe"


def item_touches_secret_root(item: dict) -> bool:
    return any(isinstance(op, dict) and op.get("kind", "").startswith("json_") and json_root(op) == "env"
               for op in item.get("ops") or [])
