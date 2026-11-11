#!/usr/bin/env python3
"""Print sample prompts for one cluster of scan.json, opening only the files that cluster lists.

Read-only. Standard library only. The cluster's `files` name the sessions; each is streamed
line by line and every user message is re-hashed with the key the scan used (`prompt_key`
for exact clusters, `near_key` with --near). A secret-shaped prompt prints as a redaction
line, never as text. After the samples, one line per session reports how often it committed
and how often the user interrupted, so a reader can keep samples from sessions that ended well.
Usage: prompt_samples.py --scan scan.json --hash <h> [--near] [--max 3] [--population interactive]
"""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import scan_commands  # noqa: E402
import scan_lib  # noqa: E402
import scan_patterns  # noqa: E402
from redact import has_secret  # noqa: E402  (on sys.path through scan_lib)

MAX_CHARS = 600
TRUNCATED = " [truncated]"
REDACTED = "[redacted: secret-shaped]"
COMMIT_PREFIX = "git commit"
NOT_FOUND_EXIT = 2


def exact_hash(text):
    return scan_lib.prompt_key(text).split(":")[0]


def exact_rows(population_summary):
    return population_summary.get("repeated_prompts", [])


def near_rows(population_summary):
    return (population_summary.get("patterns") or {}).get("near_duplicate_prompts", [])


# (rows in scan.json, key the scan hashed with, name of the rows for the error message)
EXACT_MODE = (exact_rows, exact_hash, "repeated_prompts")
NEAR_MODE = (near_rows, scan_patterns.near_key, "patterns.near_duplicate_prompts")


def find_cluster(rows, digest):
    return next((r for r in rows if r.get("hash") == digest), None)


def prompt_texts(event):
    """Text blocks of a user event that the scan hashed (tool results and boilerplate excluded)."""
    if event.get("type") != "user":
        return
    content = (event.get("message") or {}).get("content")
    blocks = [content] if isinstance(content, str) else (content if isinstance(content, list) else [])
    for block in blocks:
        text = block if isinstance(block, str) else (block.get("text", "") if isinstance(block, dict) and block.get("type") == "text" else None)
        if text and text.strip() and not scan_lib.is_boilerplate(text):
            yield text


def commits_in(event):
    """Bash tool_use blocks in an assistant event whose command contains a `git commit` segment."""
    if event.get("type") != "assistant":
        return 0
    content = (event.get("message") or {}).get("content")
    blocks = content if isinstance(content, list) else []
    commands = [str((b.get("input") or {}).get("command", "")) for b in blocks
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "Bash"]
    return sum(1 for cmd in commands if _has_commit(cmd))


def _has_commit(cmd):
    return any(scan_commands.prefix_of_words(words) == COMMIT_PREFIX for words in scan_commands.segments(cmd) or [] if words)


class SessionStats:
    def __init__(self, name):
        self.name = name
        self.commits = 0
        self.interrupts = 0

    def line(self):
        return f"session {self.name} commits={self.commits} interrupts={self.interrupts}"


def stream_session(path, name):
    """Yield `(line_number, text, stats)` for every prompt in the file; stats fill in as the file is read."""
    stats = SessionStats(name)
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line_number, raw in enumerate(fh, 1):
            if scan_lib.SIG["interrupts"] in raw:
                stats.interrupts += 1
            try:
                event = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            stats.commits += commits_in(event)
            for text in prompt_texts(event):
                yield line_number, text, stats


def render(text):
    if has_secret(text):
        return REDACTED
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS] + TRUNCATED


def locate(root, name):
    """`<project-dir>/<name>` under root, or None: session ids are unique, so one glob is enough."""
    found = glob.glob(os.path.join(root, "*", name))
    return os.path.relpath(found[0], root) if found else None


def print_samples(root, cluster, matches, limit):
    """Print up to `limit` prompts for which `matches(text)` holds, then one stats line per session opened."""
    printed, stats_lines = 0, []
    for name in cluster.get("files", []):
        rel = locate(root, name)
        if rel is None:
            stats_lines.append(f"session {name} missing")
            continue
        stats = SessionStats(rel)
        for line_number, text, stats in stream_session(os.path.join(root, rel), rel):
            if printed < limit and matches(text):
                print(f"{rel}:{line_number}\n{render(text)}\n")
                printed += 1
        stats_lines.append(stats.line())
    for line in stats_lines:
        print(line)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scan", required=True, help="scan.json written by scan.py")
    ap.add_argument("--hash", required=True, help="12-char cluster hash from scan.json")
    ap.add_argument("--near", action="store_true", help="look the hash up in patterns.near_duplicate_prompts")
    ap.add_argument("--max", type=int, default=3)
    ap.add_argument("--population", default="interactive", choices=("interactive", "headless", "subagent"))
    ap.add_argument("--root", default=scan_lib.PROJECTS_ROOT, help="projects directory; files are found at <root>/*/<file>")
    a = ap.parse_args()
    with open(a.scan, encoding="utf-8") as fh:
        scan = json.load(fh)
    rows_of, key_of, rows_name = NEAR_MODE if a.near else EXACT_MODE
    cluster = find_cluster(rows_of(scan.get(a.population) or {}), a.hash)
    if cluster is None:
        print(f"hash {a.hash} not in {a.population}.{rows_name} of {a.scan}", file=sys.stderr)
        sys.exit(NOT_FOUND_EXIT)
    print_samples(a.root, cluster, lambda text: key_of(text) == a.hash, a.max)


if __name__ == "__main__":
    main()
