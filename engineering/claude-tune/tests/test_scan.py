import json
import os
import stat
import time

import pytest

import scan_lib


def test_prefix_drops_export_values():
    assert scan_lib.prefix("export TOKEN=abc123xyz") == "export"
    assert scan_lib.prefix("TOKEN=abc python3 x.py") == "python3"
    assert scan_lib.prefix("mysql -pSECRET db") == "mysql"


def test_prefix_known_tool_keeps_subcommand():
    assert scan_lib.prefix("git -C /x status --porcelain") == "git status"
    assert scan_lib.prefix("cd /a && gh pr view 12") == "gh pr"
    assert scan_lib.prefix("/usr/bin/git push -q") == "git push"
    assert scan_lib.prefix("kubectl -n ns get pods") == "kubectl get"


def test_prefix_unknown_tool_is_basename_only():
    assert scan_lib.prefix("/tmp/x/run.sh --token abc") == "run.sh"
    assert scan_lib.prefix("echo sk_live_abc") == "echo"


def test_hook_key_is_basename():
    assert scan_lib.hook_key('node "/x/y/run_hook.js" --flag') == "run_hook.js"
    assert scan_lib.hook_key("curl https://x/?token=abc") == "curl"


def test_prompt_key_is_hashed():
    key = scan_lib.prompt_key("merged, proceed with the next one")
    assert "merged" not in key and len(key.split(":")[0]) == 12 and key.endswith(":33")


def test_write_summary_0600_and_refuses_secret(tmp_path):
    out = tmp_path / "s.json"
    scan_lib.write_summary({"ok": 1}, str(out))
    assert stat.S_IMODE(os.stat(out).st_mode) == 0o600 and json.loads(out.read_text()) == {"ok": 1}
    with pytest.raises(ValueError, match="secret"):
        scan_lib.write_summary({"cmd": "token sk_live_abcdef0123"}, str(tmp_path / "bad.json"))


def _event(kind, ts, **extra):
    base = {"type": kind, "timestamp": ts}
    base.update(extra)
    return json.dumps(base)


def test_events_before_cutoff_skipped(tmp_path):
    old_ts = "2020-01-01T00:00:00Z"
    new_ts = "2099-01-01T00:00:00Z"
    f = tmp_path / "s.jsonl"
    f.write_text("\n".join([
        json.dumps({"type": "user", "timestamp": old_ts, "entrypoint": "cli", "message": {"content": "old prompt"}}),
        json.dumps({"type": "user", "timestamp": new_ts, "message": {"content": "new prompt here"}}),
    ]) + "\n")
    pop = scan_lib.Pop()
    scan_lib.scan_file(str(f), lambda e, p: pop, 10 ** 9, cutoff=time.mktime((2021, 1, 1, 0, 0, 0, 0, 0, -1)))
    assert pop.user_msgs == 1


def test_non_dict_event_skipped(tmp_path):
    f = tmp_path / "s.jsonl"
    f.write_text('"just a string"\n[1,2]\n{"type":"user","message":"not a dict"}\n')
    pop = scan_lib.Pop()
    assert scan_lib.scan_file(str(f), lambda e, p: pop, 10 ** 9, cutoff=0) == "ok"
    assert pop.user_msgs == 0


def test_functions_are_short():
    import inspect
    for name in ("scan_file", "classify_line", "record_user", "record_assistant"):
        fn = getattr(scan_lib, name)
        assert len(inspect.getsource(fn).splitlines()) <= 30, name
