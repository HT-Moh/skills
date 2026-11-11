"""Recurring 3-step tool sequences, counted by distinct session, with no arguments kept."""
import json

import scan_lib
import scan_patterns
import scan_sequences
from test_scan_patterns import bash, tool_use


def _scan_many(tmp_path, per_session):
    """`per_session` maps a file name to its events; all land in one Pop."""
    pop = scan_lib.Pop()
    for name, events in per_session.items():
        f = tmp_path / name
        f.write_text("\n".join(json.dumps(e) for e in events) + "\n")
        scan_lib.scan_file(str(f), lambda e, p: pop, 10 ** 9, cutoff=0)
    return pop


def _rows(pop):
    return scan_patterns.summary(pop.patterns, len(pop.sessions))["recurring_tool_sequences"]


READ_EDIT_TEST = [tool_use("a", "Read", {"file_path": "/r/x.py"}), tool_use("b", "Edit", {"file_path": "/r/x.py"}),
                  bash("c", "pytest -q tests/secret_test.py")]


def test_token_reduces_bash_skill_and_agent_without_arguments():
    assert scan_sequences.token_of("Bash", {"command": "git commit -m 'secret message'"}) == "Bash:git commit"
    assert scan_sequences.token_of("Skill", {"skill": "superpowers:tdd", "args": "secret"}) == "Skill:superpowers:tdd"
    assert scan_sequences.token_of("Agent", {"subagent_type": "Explore", "prompt": "secret"}) == "Agent:Explore"
    assert scan_sequences.token_of("Read", {"file_path": "/secret/x"}) == "Read"


def test_sequence_counts_distinct_sessions_at_threshold_three(tmp_path):
    pop = _scan_many(tmp_path, {f"{i}.jsonl": READ_EDIT_TEST for i in range(3)})
    assert _rows(pop) == [{"sequence": "Read > Edit > Bash:pytest", "sessions": 3}]


def test_sequence_in_two_sessions_is_below_threshold(tmp_path):
    pop = _scan_many(tmp_path, {f"{i}.jsonl": READ_EDIT_TEST for i in range(2)})
    assert _rows(pop) == []


def test_same_sequence_twice_in_one_session_counts_once(tmp_path):
    pop = _scan_many(tmp_path, {"one.jsonl": READ_EDIT_TEST + READ_EDIT_TEST, "two.jsonl": READ_EDIT_TEST})
    assert pop.patterns.sequences["Read > Edit > Bash:pytest"] == {"one.jsonl", "two.jsonl"}


def test_identical_triple_is_skipped(tmp_path):
    pop = _scan_many(tmp_path, {f"{i}.jsonl": [bash("a", "ls"), bash("b", "ls"), bash("c", "ls")] for i in range(3)})
    assert "Bash:ls > Bash:ls > Bash:ls" not in pop.patterns.sequences


def test_sliding_window_yields_every_three_gram(tmp_path):
    events = [tool_use("a", "Grep", {"pattern": "x"}), tool_use("b", "Read", {"file_path": "/r"}),
              tool_use("c", "Edit", {"file_path": "/r"}), bash("d", "pytest")]
    pop = _scan_many(tmp_path, {"one.jsonl": events})
    assert set(pop.patterns.sequences) == {"Grep > Read > Edit", "Read > Edit > Bash:pytest"}


def test_summary_sorted_by_sessions_and_free_of_arguments(tmp_path):
    common = [tool_use("a", "Glob", {"pattern": "**/secret"}), tool_use("b", "Read", {"file_path": "/secret"}), bash("c", "git status")]
    sessions = {f"c{i}.jsonl": common for i in range(4)}
    sessions.update({f"r{i}.jsonl": READ_EDIT_TEST for i in range(3)})
    rows = _rows(_scan_many(tmp_path, sessions))
    assert [r["sessions"] for r in rows] == [4, 3]
    assert "secret" not in json.dumps(rows)
