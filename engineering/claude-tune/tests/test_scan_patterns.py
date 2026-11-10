"""Structural patterns the scanner counts without storing content."""
import json

import scan_lib
import scan_patterns

T0 = "2099-01-01T00:00:00Z"


def _ts(seconds):
    return f"2099-01-01T00:{seconds // 60:02d}:{seconds % 60:02d}Z"


def user_text(text, seconds=0):
    return {"type": "user", "timestamp": _ts(seconds), "entrypoint": "cli", "message": {"content": text}}


def tool_use(uid, name, inp, seconds=0, msg_id=None, usage=None, text=None):
    content = [{"type": "tool_use", "id": uid, "name": name, "input": inp}]
    if text:
        content.insert(0, {"type": "text", "text": text})
    msg = {"id": msg_id or f"m{uid}", "model": "x", "content": content}
    if usage:
        msg["usage"] = usage
    return {"type": "assistant", "timestamp": _ts(seconds), "message": msg}


def assistant_text(text, seconds=0, msg_id="mt"):
    return {"type": "assistant", "timestamp": _ts(seconds),
            "message": {"id": msg_id, "model": "x", "content": [{"type": "text", "text": text}]}}


def tool_result(uid, content="ok", seconds=1, is_error=False):
    block = {"type": "tool_result", "tool_use_id": uid, "content": content, "is_error": is_error}
    return {"type": "user", "timestamp": _ts(seconds), "message": {"content": [block]}}


def scan(tmp_path, events, name="s.jsonl"):
    f = tmp_path / name
    f.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    pop = scan_lib.Pop()
    scan_lib.scan_file(str(f), lambda e, p: pop, 10 ** 9, cutoff=0)
    return pop


def bash(uid, cmd, seconds=0):
    return tool_use(uid, "Bash", {"command": cmd}, seconds)


def test_revert_forms_counted_by_prefix(tmp_path):
    pop = scan(tmp_path, [bash("a", "git checkout -- src/x.py"), bash("b", "git checkout main"),
                          bash("c", "git reset --hard HEAD~1"), bash("d", "git stash"), bash("e", "git restore x")])
    assert pop.patterns.reverts == {"git checkout --": 1, "git reset": 1, "git stash": 1, "git restore": 1}


def test_dangerous_forms_counted(tmp_path):
    pop = scan(tmp_path, [bash("a", "rm -rf build"), bash("b", "git push --force origin x"),
                          bash("c", "git push --force-with-lease"), bash("d", "git commit --no-verify -m x"),
                          bash("e", "cd /x && git clean -fdx")])
    assert pop.patterns.dangerous == {"rm -rf": 1, "git push --force": 1, "--no-verify": 1, "git clean -f": 1}


def test_credential_reads_counted_without_path(tmp_path):
    pop = scan(tmp_path, [tool_use("a", "Read", {"file_path": "/repo/.env"}),
                          tool_use("b", "Read", {"file_path": "/home/u/.ssh/id_ed25519"}),
                          tool_use("c", "Read", {"file_path": "/repo/src/main.py"}),
                          tool_use("d", "Read", {"file_path": "/repo/.env.example"})])
    assert pop.patterns.credential_reads == 2


def test_premature_session_edits_before_any_read(tmp_path):
    pop = scan(tmp_path, [user_text("fix it"), tool_use("a", "Edit", {"file_path": "/r/x.py"})], "a.jsonl")
    scan(tmp_path, [user_text("fix it"), tool_use("a", "Read", {"file_path": "/r/x.py"}),
                    tool_use("b", "Edit", {"file_path": "/r/x.py"})], "b.jsonl")
    assert pop.patterns.premature_sessions == 1


def test_file_churn_counts_paths_edited_over_five_times(tmp_path):
    edits = [tool_use(f"e{i}", "Edit", {"file_path": "/r/x.py"}) for i in range(6)]
    pop = scan(tmp_path, edits + [tool_use("w", "Write", {"file_path": "/r/y.py"})])
    assert pop.patterns.churn_files == 1


def test_repeated_bash_counts_identical_consecutive_commands(tmp_path):
    pop = scan(tmp_path, [bash("a", "pytest -q"), bash("b", "pytest -q"), bash("c", "ls"), bash("d", "pytest -q")])
    assert pop.patterns.repeated_bash == 1


def test_duplicate_reads_and_oversized_results(tmp_path):
    big = "x" * 20001
    pop = scan(tmp_path, [tool_use("a", "Read", {"file_path": "/r/x.py"}), tool_result("a", big, 1),
                          tool_use("b", "Read", {"file_path": "/r/x.py"}, 2), tool_result("b", big, 3),
                          tool_use("c", "Grep", {"pattern": "q"}, 4), tool_result("c", [{"type": "text", "text": "short"}], 5)])
    assert pop.patterns.duplicate_reads == 1
    assert pop.patterns.duplicate_read_chars == 20001
    assert pop.patterns.oversized_results == {"Read": 2}


def test_tool_wait_per_non_bash_tool(tmp_path):
    pop = scan(tmp_path, [tool_use("a", "Read", {"file_path": "/r/x.py"}, 0), tool_result("a", "ok", 7),
                          bash("b", "ls", 10), tool_result("b", "ok", 11)])
    assert pop.patterns.tool_wait_s == {"Read": 7} and pop.patterns.tool_wait_n == {"Read": 1}
    assert pop.bash_time == {"ls": 1}


def test_nudge_prompts_counted(tmp_path):
    pop = scan(tmp_path, [user_text("proceed"), user_text("Continue."), user_text("yes"),
                          user_text("proceed with the deploy")])
    assert pop.patterns.nudges == 3


def test_near_duplicate_key_ignores_numbers_paths_and_quotes():
    k1 = scan_patterns.near_key("merge PR 12 in /a/b and say 'done'")
    k2 = scan_patterns.near_key("merge PR 345 in /c/d/e and say \"ok\"")
    assert k1 == k2 and "merge" not in k1 and len(k1) == 12
    assert scan_patterns.near_key("deploy staging") != k1


def test_near_duplicates_grouped_across_sessions(tmp_path):
    pop = scan(tmp_path, [user_text("merge PR 12")], "a.jsonl")
    for n in ("77", "4567"):
        f = tmp_path / f"{n}.jsonl"
        f.write_text(json.dumps(user_text(f"merge PR {n}")) + "\n")
        scan_lib.scan_file(str(f), lambda e, p: pop, 10 ** 9, cutoff=0)
    assert max(len(s) for s in pop.patterns.near_prompts.values()) == 3


def test_done_claim_without_test_run_since_last_prompt(tmp_path):
    pop = scan(tmp_path, [user_text("fix", 0), tool_use("a", "Edit", {"file_path": "/r/x.py"}, 1),
                          assistant_text("All tests pass now.", 2, "m1"),
                          user_text("next", 3), bash("b", "pytest -q", 4), tool_result("b", "ok", 5),
                          assistant_text("Tests pass.", 6, "m2")])
    assert pop.patterns.done_claims == 2 and pop.patterns.done_without_verify == 1


def test_interrupt_attributed_to_preceding_tool(tmp_path):
    pop = scan(tmp_path, [bash("a", "kubectl rollout status x"), user_text("[Request interrupted by user]", 1),
                          tool_use("b", "Edit", {"file_path": "/r/x.py"}, 2), user_text("[Request interrupted by user for tool use]", 3)])
    assert pop.patterns.interrupt_before == {"Bash": 1, "Edit": 1}


def test_orphaned_agents_counted_at_session_end(tmp_path):
    pop = scan(tmp_path, [tool_use("a", "Agent", {"subagent_type": "x"}), tool_use("b", "Agent", {"subagent_type": "x"}),
                          tool_result("a", "report", 5)])
    assert pop.patterns.orphaned_agents == 1


def test_cache_miss_ratio_per_session(tmp_path):
    usage1 = {"input_tokens": 0, "cache_creation_input_tokens": 300, "cache_read_input_tokens": 700, "output_tokens": 1}
    usage2 = {"input_tokens": 0, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 900, "output_tokens": 1}
    pop = scan(tmp_path, [tool_use("a", "Read", {"file_path": "/r/x"}, 0, "m1", usage1),
                          tool_use("b", "Read", {"file_path": "/r/y"}, 1, "m2", usage2)])
    assert pop.patterns.cache_miss_ratio == [0.2]


def test_summary_has_no_paths_or_prompt_text(tmp_path):
    pop = scan(tmp_path, [user_text("merge PR 12 in /secret/dir"), tool_use("a", "Read", {"file_path": "/secret/.env"}),
                          bash("b", "rm -rf /secret/build")])
    text = json.dumps(scan_patterns.summary(pop.patterns, len(pop.sessions)))
    assert "secret" not in text and "merge" not in text


def test_pattern_functions_are_short():
    import inspect
    for name, fn in inspect.getmembers(scan_patterns, inspect.isfunction):
        assert len(inspect.getsource(fn).splitlines()) <= 30, name
