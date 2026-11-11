"""`prompt_samples.py` reopens only the files a cluster lists and prints redacted samples."""
import json
import subprocess
import sys
from pathlib import Path

import scan
import scan_lib
import scan_patterns

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "prompt_samples.py"
SECRET_PROMPT = "set the key sk_live_4242424242424242abcd then deploy"


def _user(text):
    return {"type": "user", "timestamp": "2099-01-01T00:00:00Z", "entrypoint": "cli", "message": {"content": text}}


def _bash(cmd):
    block = {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": cmd}}
    return {"type": "assistant", "timestamp": "2099-01-01T00:00:01Z", "message": {"id": "m1", "model": "x", "content": [block]}}


def _write_population(tmp_path, sessions):
    """`sessions` maps `<project>/<file>` to event lists; returns the scan.json path."""
    pop = scan_lib.Pop()
    for rel, events in sessions.items():
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("".join(json.dumps(e) + "\n" for e in events))
        scan_lib.scan_file(str(f), lambda e, p: pop, 10 ** 9, cutoff=0)
    out = tmp_path / "scan.json"
    out.write_text(json.dumps({"interactive": scan.population_summary(pop)}))
    return out


def _run(scan_path, tmp_path, *extra):
    argv = [sys.executable, str(SCRIPT), "--scan", str(scan_path), "--root", str(tmp_path), *extra]
    return subprocess.run(argv, capture_output=True, text=True, timeout=60)


def test_exact_cluster_samples_with_file_line_and_session_stats(tmp_path):
    first = [_user("deploy to staging"), _bash("git add -A && git commit -m x"), _user("deploy to staging"),
             _user("[Request interrupted by user]"), _user("other thing")]
    others = {f"p/{i}.jsonl": [_user("deploy to staging")] for i in (2, 3)}
    scan_path = _write_population(tmp_path, {"p/1.jsonl": first, **others})
    r = _run(scan_path, tmp_path, "--hash", scan_lib.prompt_key("deploy to staging").split(":")[0], "--max", "2")
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert lines[0] == "p/1.jsonl:1" and lines[1] == "deploy to staging"
    assert "p/1.jsonl:3" in lines and lines.count("deploy to staging") == 2
    assert "session p/1.jsonl commits=1 interrupts=1" in lines
    assert "other thing" not in r.stdout


def test_near_cluster_uses_near_key(tmp_path):
    scan_path = _write_population(tmp_path, {"p/1.jsonl": [_user(f"merge PR {n}") for n in range(5)]})
    r = _run(scan_path, tmp_path, "--near", "--hash", scan_patterns.near_key("merge PR 0"), "--max", "1")
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines()[:2] == ["p/1.jsonl:1", "merge PR 0"]


def test_secret_shaped_prompt_prints_as_redacted(tmp_path):
    scan_path = _write_population(tmp_path, {"p/1.jsonl": [_user(SECRET_PROMPT)] * 5})
    r = _run(scan_path, tmp_path, "--hash", scan_lib.prompt_key(SECRET_PROMPT).split(":")[0], "--max", "1")
    assert r.returncode == 0, r.stderr
    assert "sk_live" not in r.stdout and "[redacted: secret-shaped]" in r.stdout.splitlines()


def test_long_prompt_is_truncated_to_600_chars(tmp_path):
    long_prompt = "word " * 300
    scan_path = _write_population(tmp_path, {"p/1.jsonl": [_user(long_prompt)] * 5})
    r = _run(scan_path, tmp_path, "--hash", scan_lib.prompt_key(long_prompt).split(":")[0], "--max", "1")
    sample = r.stdout.splitlines()[1]
    assert sample.startswith("word word") and len(sample) <= 600 + len(" [truncated]")


def test_unknown_hash_exits_2_with_one_line(tmp_path):
    scan_path = _write_population(tmp_path, {"p/1.jsonl": [_user("x")]})
    r = _run(scan_path, tmp_path, "--hash", "0123456789ab")
    assert r.returncode == 2 and r.stdout == ""
    assert len(r.stderr.strip().splitlines()) == 1 and "0123456789ab" in r.stderr


def test_cluster_files_are_resolved_through_the_project_dir(tmp_path):
    scan_path = _write_population(tmp_path, {"proj-a/1.jsonl": [_user("deploy to staging")] * 5})
    rows = json.loads(scan_path.read_text())["interactive"]["repeated_prompts"]
    assert rows[0]["files"] == ["1.jsonl"]
    r = _run(scan_path, tmp_path, "--hash", scan_lib.prompt_key("deploy to staging").split(":")[0], "--max", "1")
    assert r.stdout.splitlines()[0] == "proj-a/1.jsonl:1"


def test_sampler_writes_nothing(tmp_path):
    scan_path = _write_population(tmp_path, {"p/1.jsonl": [_user("deploy to staging")] * 5})
    before = sorted(p.name for p in tmp_path.rglob("*"))
    _run(scan_path, tmp_path, "--hash", scan_lib.prompt_key("deploy to staging").split(":")[0])
    assert sorted(p.name for p in tmp_path.rglob("*")) == before
