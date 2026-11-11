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


def test_hook_key_ignores_inline_code_and_odd_scripts():
    assert scan_lib.hook_key("node -e 'console.log(process.env.TOKEN)'") == "node"
    assert scan_lib.hook_key("python3 -c 'print(1)'") == "python3"
    assert scan_lib.hook_key("bash sk_live_abc") == "bash"
    assert scan_lib.hook_key("node /x/run_hook.mjs") == "run_hook.mjs"


def test_prefix_subcommand_must_look_like_a_verb():
    assert scan_lib.prefix("git -C /x 'sk_live_abc'") == "git"
    assert scan_lib.prefix("gh --repo o/r pr view 12") == "gh"
    assert scan_lib.prefix("docker run --rm img") == "docker run"


def test_prefix_respects_quotes_and_unparsable_input():
    assert scan_lib.prefix("echo 'a && b'") == "echo"
    assert scan_lib.prefix("echo 'unterminated") == "(unparsed)"
    assert scan_lib.prefix("TOKEN='a b' python3 x.py") == "python3"


def _user(text):
    return json.dumps({"type": "user", "timestamp": "2099-01-01T00:00:00Z", "entrypoint": "cli", "message": {"content": text}})


def _scan_sessions(tmp_path, sessions):
    """`sessions` maps `<project>/<file>.jsonl` to a list of prompts; returns the scanned Pop."""
    pop = scan_lib.Pop()
    for rel, prompts in sessions.items():
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("".join(_user(p) + "\n" for p in prompts))
        scan_lib.scan_file(str(f), lambda e, p: pop, 10 ** 9, cutoff=0)
    return pop


def _hash(text):
    return scan_lib.prompt_key(text).split(":")[0]


def test_session_name_is_relative_to_the_project_dir():
    assert scan_lib.session_name("/h/.claude/projects/-tmp-x-59a7963b-a3fd/abc.jsonl") == "abc.jsonl"
    assert scan_lib.session_name("/h/.claude/projects/-tmp-x/sess1/subagents/agent-a1.jsonl") == "sess1/subagents/agent-a1.jsonl"


def test_summary_with_uuid_session_files_passes_the_secret_check(tmp_path):
    import scan
    project = "-tmp-claude-1000--media-x-59a7963b-a3fd-4185-bfe3-025363697695-scratchpad-skillwork"
    prompts = ["run the deploy"] * 5
    pop = _scan_sessions(tmp_path, {f"{project}/7c9e6679-7425-40de-944b-e07fc1f90ae7.jsonl": prompts})
    scan_lib.write_summary(scan.population_summary(pop), str(tmp_path / "out.json"))
    assert pop.sessions == {"7c9e6679-7425-40de-944b-e07fc1f90ae7.jsonl"}


def test_prompt_cluster_counts_occurrences_inside_one_session(tmp_path):
    import scan
    pop = _scan_sessions(tmp_path, {"p/one.jsonl": ["run the deploy"] * 5 + ["something else"]})
    rows = scan.population_summary(pop)["repeated_prompts"]
    assert len(rows) == 1
    row = rows[0]
    assert row["sessions"] == 1 and row["occurrences"] == 5 and row["files"] == ["one.jsonl"]
    assert row["hash"] == _hash("run the deploy") and row["len"] == 14


def test_prompt_cluster_threshold_three_sessions_or_five_occurrences(tmp_path):
    import scan
    sessions = {f"p/{i}.jsonl": ["merge it", "twice"] for i in range(3)}
    sessions["p/4.jsonl"] = ["twice"] * 2 + ["lonely"] * 4
    pop = _scan_sessions(tmp_path, sessions)
    rows = scan.population_summary(pop)["repeated_prompts"]
    assert {r["hash"] for r in rows} == {_hash("merge it"), _hash("twice")}


def test_prompt_cluster_sorted_by_occurrences_and_files_capped_at_five(tmp_path):
    import scan
    sessions = {f"p/{i}.jsonl": ["common prompt"] for i in range(7)}
    sessions["p/big.jsonl"] = ["loud prompt"] * 9
    pop = _scan_sessions(tmp_path, sessions)
    rows = scan.population_summary(pop)["repeated_prompts"]
    assert [r["occurrences"] for r in rows] == [9, 7]
    assert len(rows[1]["files"]) == 5 and all(f.endswith(".jsonl") and "/" not in f for f in rows[1]["files"])


def test_print_summary_accepts_cluster_objects(tmp_path, capsys):
    import scan
    pop = _scan_sessions(tmp_path, {"p/one.jsonl": ["run the deploy"] * 5})
    summary = scan.population_summary(pop)
    scan.print_summary({"interactive": summary, "headless": summary, "subagent": summary,
                        "subagent_types_from_meta": [], "files": 1, "skipped_over_max_mb": 0})
    assert "repeated_prompts(hash,sessions,occ)=" in capsys.readouterr().out
