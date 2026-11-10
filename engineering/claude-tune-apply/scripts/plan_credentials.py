"""Literal credentials in plan ops: any value under a credential-named key must be a ${VAR} reference."""
import re

from redact import key_is_sensitive

VAR_REF_RE = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}")  # a bare reference; no :-default under a credential key


def _literal_credentials(it: dict) -> list[str]:
    """Any string written at or below a credential-named key must be exactly one ${VAR} reference."""
    errs = []
    for op in it.get("ops") or []:
        if not isinstance(op, dict) or not str(op.get("kind", "")).startswith("json_"):
            continue
        path = [str(k) for k in (op.get("path") or [])]
        inherited = any(key_is_sensitive(k) for k in path)
        for field in ("value", "values"):
            if field in op:
                for key, _ in _credential_leaves(path[-1] if path else "", op[field], inherited):
                    errs.append(f"item {it.get('id', '?')}: op sets a literal under credential key {key}; use ${{VAR}}")
    return errs


def _credential_leaves(key: str, node, inherited: bool):
    """(key, value) pairs where a non-reference string sits under a credential-named key or ancestor."""
    sensitive = inherited or key_is_sensitive(key)
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _credential_leaves(str(k), v, sensitive)
    elif isinstance(node, list):
        for v in node:
            yield from _credential_leaves(key, v, sensitive)
    elif isinstance(node, str) and node and sensitive and not VAR_REF_RE.fullmatch(node):
        yield key, node
