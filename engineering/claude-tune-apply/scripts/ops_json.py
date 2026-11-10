"""JSON operations: set, delete, append, upsert. Each previews against the current text.

A `json_*` op may carry `expect`: the value the plan saw at its path (`null` for absent).
The preview refuses when the live value differs, so a plan never overwrites an edit it
did not see.
"""
import json

from ops_base import OpResult, read_text

JSON_INDENT = 2
_MISSING = object()


def _load_doc(text, path):
    """Parse the file text; a missing file is an empty object, an empty or bad file is an error."""
    if text is None:
        return {}
    if not text.strip():
        raise ValueError(f"{path} is empty, not JSON")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc


def _dump(doc):
    return json.dumps(doc, indent=JSON_INDENT, ensure_ascii=False) + "\n"


def _json_parent(doc, keys, create):
    """The object holding the last key; raises ValueError when something on the way is not an object."""
    node = doc
    for k in keys:
        if not isinstance(node, dict):
            raise ValueError(f"path element {k!r} is not under an object")
        if k not in node:
            if not create:
                return None
            node[k] = {}
        node = node[k]
    if not isinstance(node, dict) and node is not None:
        raise ValueError(f"{'.'.join(map(str, keys)) or '<root>'} is not an object")
    return node


def _current_value(doc, keys):
    node = doc
    for k in keys:
        if not isinstance(node, dict) or k not in node:
            return _MISSING
        node = node[k]
    return node


def _check_expect(op, doc):
    """Error text when the op carries `expect` and the live value differs; else None."""
    if "expect" not in op:
        return None
    current = _current_value(doc, op["path"])
    expected = op["expect"]
    if expected is None and current is _MISSING:
        return None
    if expected is not None and current is not _MISSING and current == expected:
        return None
    shown = "absent" if current is _MISSING else "a different value"
    return f"expect failed: {'.'.join(op['path'])} is {shown}; the plan saw {'absent' if expected is None else 'another value'}"


def _result(op, path, before, mutate):
    try:
        doc = _load_doc(before, path)
        err = _check_expect(op, doc)
        if err:
            return OpResult(kind=op["kind"], path=path, before=before, errors=[err])
        original = json.dumps(doc, sort_keys=True)
        mutate(doc)
    except ValueError as exc:
        return OpResult(kind=op["kind"], path=path, before=before, errors=[str(exc)])
    changed = json.dumps(doc, sort_keys=True) != original
    after = _dump(doc) if (changed or before is not None) else None
    return OpResult(kind=op["kind"], path=path, before=before, after=after if changed else before, changed=changed)


def preview_json_set(op, path, overlay=None):
    keys = list(op["path"])

    def mutate(doc):
        parent = _json_parent(doc, keys[:-1], create=True)
        parent[keys[-1]] = op.get("value")
    return _result(op, path, read_text(path, overlay), mutate)


def preview_json_delete(op, path, overlay=None):
    keys = list(op["path"])

    def mutate(doc):
        parent = _json_parent(doc, keys[:-1], create=False)
        if isinstance(parent, dict):
            parent.pop(keys[-1], None)
    return _result(op, path, read_text(path, overlay), mutate)


def preview_json_append(op, path, overlay=None):
    keys = list(op["path"])
    values = op.get("values")
    if not isinstance(values, list):
        return OpResult(kind="json_append", path=path, errors=["values must be a list"])

    def mutate(doc):
        lst = _list_at(doc, keys)
        for v in values:
            if v not in lst:
                lst.append(v)
    return _result(op, path, read_text(path, overlay), mutate)


def preview_json_upsert(op, path, overlay=None):
    keys = list(op["path"])
    match = op.get("match")
    if not isinstance(match, dict) or not match:
        return OpResult(kind="json_upsert", path=path, errors=["match must be a non-empty object"])

    def mutate(doc):
        lst = _list_at(doc, keys)
        for n, element in enumerate(lst):
            if isinstance(element, dict) and all(element.get(k) == v for k, v in match.items()):
                lst[n] = op.get("value")
                return
        lst.append(op.get("value"))
    return _result(op, path, read_text(path, overlay), mutate)


def _list_at(doc, keys):
    parent = _json_parent(doc, keys[:-1], create=True)
    lst = parent.setdefault(keys[-1], [])
    if not isinstance(lst, list):
        raise ValueError(f"{'.'.join(map(str, keys))} is not a list")
    return lst


PREVIEWERS = {"json_set": preview_json_set, "json_delete": preview_json_delete,
              "json_append": preview_json_append, "json_upsert": preview_json_upsert}
