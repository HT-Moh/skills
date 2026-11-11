"""Structural patterns counted while streaming a transcript, with no content kept.

Each detector reads fields the scanner already parses (tool names, command tokens,
file paths, usage, timestamps) and increments a counter. Paths become hashes, commands
become prefixes or named forms, prompts become a normalised hash.
"""
import collections
import hashlib
import re

import scan_commands

EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
LOOK_TOOLS = ("Read", "Grep", "Glob", "Bash", "Agent", "Skill", "WebFetch", "WebSearch")
CHURN_EDITS = 5
OVERSIZED_CHARS = 20000
INTERRUPT = "[Request interrupted by user"
CREDENTIAL_PATH_RE = re.compile(r"(^|/)(\.env(\.[^/]*)?|id_(rsa|dsa|ecdsa|ed25519)|credentials(\.json)?|\.netrc|[^/]*\.(pem|key|p12|pfx))$")
CREDENTIAL_EXAMPLE_RE = re.compile(r"\.(example|sample|template|dist)$")
NUDGES = frozenset({"proceed", "continue", "yes", "y", "ok", "okay", "go", "go on", "go ahead", "next", "do it",
                    "continue please", "proceed please", "yes proceed", "ok proceed"})
TEST_RE = re.compile(r"\b(pytest|jest|vitest|mocha|cargo test|go test|make (test|check)|(npm|pnpm|yarn|bun) (run )?test|"
                     r"tox|unittest|rspec|phpunit|ruff|mypy|tsc|eslint|golangci-lint)\b")
DONE_RE = re.compile(r"\b(tests? (now )?(pass|passing|green)|all green|suite (is )?green|implementation complete|"
                     r"done and (verified|tested)|verified (locally|in|with|by))\b", re.I)
NEAR_NUMBER_RE = re.compile(r"\d+")
NEAR_PATH_RE = re.compile(r"\S*/\S*")
NEAR_QUOTE_RE = re.compile(r"(\"[^\"]*\"|'[^']*'|`[^`]*`)")
NEAR_PUNCT_RE = re.compile(r"[^\w\s<>]")


def near_key(text):
    """Hash of the prompt with numbers, paths and quoted spans replaced; groups near-duplicates."""
    s = NEAR_QUOTE_RE.sub("<q>", text.lower())
    s = NEAR_PATH_RE.sub("<path>", s)
    s = NEAR_NUMBER_RE.sub("0", s)
    s = " ".join(NEAR_PUNCT_RE.sub(" ", s).split())
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]


def path_key(path):
    return hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:12]


def is_nudge(text):
    return " ".join(NEAR_PUNCT_RE.sub(" ", text.lower()).split()) in NUDGES


def is_credential_path(path):
    path = str(path)
    return bool(CREDENTIAL_PATH_RE.search(path)) and not CREDENTIAL_EXAMPLE_RE.search(path)


def revert_form(words):
    """`git checkout --`, `git reset`, `git revert`, `git stash`, `git restore`, or ''."""
    p = scan_commands.prefix_of_words(words)
    if p == "git checkout":
        return "git checkout --" if "--" in words else ""
    return p if p in ("git reset", "git revert", "git stash", "git restore") else ""


def dangerous_forms(words):
    """Named destructive forms present in one simple command."""
    p = scan_commands.prefix_of_words(words)
    flags = set(words[1:])
    out = []
    if p == "rm" and any(re.fullmatch(r"-[a-zA-Z]*[rR][a-zA-Z]*f[a-zA-Z]*|-[a-zA-Z]*f[a-zA-Z]*[rR][a-zA-Z]*", f) for f in flags):
        out.append("rm -rf")
    if p == "git push" and ("--force" in flags or "-f" in flags):
        out.append("git push --force")
    if p == "git reset" and "--hard" in flags:
        out.append("git reset --hard")
    if p == "git clean" and any(re.fullmatch(r"-[a-zA-Z]*f[a-zA-Z]*", f) for f in flags):
        out.append("git clean -f")
    if "--no-verify" in flags:
        out.append("--no-verify")
    return out


CLUSTER_MIN_SESSIONS = 3
CLUSTER_MIN_OCCURRENCES = 5
CLUSTER_FILES_KEPT = 5
CLUSTER_ROWS_KEPT = 15


class PromptCluster:
    """Every message that hashes to one key: how many, in how many sessions, and where to look."""

    def __init__(self):
        self.sessions = set()
        self.occurrences = 0
        self.files = []

    def add(self, session_name):
        self.occurrences += 1
        if session_name not in self.sessions and len(self.files) < CLUSTER_FILES_KEPT:
            self.files.append(session_name)
        self.sessions.add(session_name)

    def is_recurring(self):
        return len(self.sessions) >= CLUSTER_MIN_SESSIONS or self.occurrences >= CLUSTER_MIN_OCCURRENCES


def cluster_rows(clusters):
    """JSON-ready rows for the recurring clusters, most occurrences first, top 15."""
    kept = sorted(((c.occurrences, k) for k, c in clusters.items() if c.is_recurring()), reverse=True)
    return [{"hash": k, "sessions": len(clusters[k].sessions), "occurrences": n, "files": list(clusters[k].files)}
            for n, k in kept[:CLUSTER_ROWS_KEPT]]


class Patterns:
    """Per-population counters; every value is a count, a ratio or a hash."""

    def __init__(self):
        self.reverts = collections.Counter()
        self.dangerous = collections.Counter()
        self.credential_reads = 0
        self.premature_sessions = 0
        self.churn_files = 0
        self.repeated_bash = 0
        self.duplicate_reads = 0
        self.duplicate_read_chars = 0
        self.oversized_results = collections.Counter()
        self.tool_wait_s = collections.Counter()
        self.tool_wait_n = collections.Counter()
        self.nudges = 0
        self.near_prompts = collections.defaultdict(PromptCluster)
        self.done_claims = 0
        self.done_without_verify = 0
        self.interrupt_before = collections.Counter()
        self.orphaned_agents = 0
        self.cache_miss_ratio = []


class Session:
    """Per-file state: open tool calls plus what the detectors need to remember."""

    def __init__(self, name):
        self.name = name
        self.pending = {}
        self.first_seen = False
        self.first_tool = None
        self.last_tool = None
        self.last_bash = None
        self.edits = collections.Counter()
        self.reads = collections.Counter()
        self.verified = False
        self.agents = set()
        self.cache_creation = 0
        self.cache_read = 0


def on_user_text(text, sess, pat):
    if INTERRUPT in text:
        pat.interrupt_before[sess.last_tool or "(none)"] += 1
        return
    sess.verified = False
    if is_nudge(text):
        pat.nudges += 1
    pat.near_prompts[near_key(text)].add(sess.name)


def on_assistant_text(text, sess, pat):
    if DONE_RE.search(text):
        pat.done_claims += 1
        if not sess.verified:
            pat.done_without_verify += 1


def on_usage(usage, sess):
    sess.cache_creation += usage.get("cache_creation_input_tokens", 0)
    sess.cache_read += usage.get("cache_read_input_tokens", 0)


def on_tool_use(block, sess, pat):
    name = block.get("name", "?")
    inp = block.get("input") or {}
    if sess.first_tool is None:
        sess.first_tool = name
    sess.last_tool = name
    if name == "Agent":
        sess.agents.add(block.get("id"))
    if name in EDIT_TOOLS:
        sess.edits[path_key(inp.get("file_path") or inp.get("notebook_path") or "")] += 1
    if name == "Read" and is_credential_path(inp.get("file_path", "")):
        pat.credential_reads += 1
    if name == "Bash":
        _on_bash(str(inp.get("command", "")), sess, pat)


def _on_bash(cmd, sess, pat):
    digest = hashlib.sha256(" ".join(cmd.split()).encode("utf-8")).hexdigest()
    if digest == sess.last_bash:
        pat.repeated_bash += 1
    sess.last_bash = digest
    if TEST_RE.search(cmd):
        sess.verified = True
    for words in scan_commands.segments(cmd) or []:
        if not words:
            continue
        if form := revert_form(words):
            pat.reverts[form] += 1
        for form in dangerous_forms(words):
            pat.dangerous[form] += 1


def result_chars(content):
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(len(b.get("text", "")) for b in content if isinstance(b, dict))
    return 0


def on_tool_result(block, call, sess, pat, elapsed):
    """`call` is (name, input) recorded at tool_use time; `elapsed` is None without timestamps."""
    name, inp = call
    sess.agents.discard(block.get("tool_use_id"))
    chars = result_chars(block.get("content"))
    if chars > OVERSIZED_CHARS:
        pat.oversized_results[name] += 1
    if name == "Read":
        key = path_key(inp.get("file_path", ""))
        sess.reads[key] += 1
        if sess.reads[key] > 1:
            pat.duplicate_reads += 1
            pat.duplicate_read_chars += chars
    if elapsed is not None and name != "Bash":
        pat.tool_wait_s[name] += elapsed
        pat.tool_wait_n[name] += 1


def finish_session(sess, pat):
    if sess.first_tool in EDIT_TOOLS:
        pat.premature_sessions += 1
    pat.churn_files += sum(1 for n in sess.edits.values() if n > CHURN_EDITS)
    pat.orphaned_agents += len(sess.agents)
    total = sess.cache_creation + sess.cache_read
    if total:
        pat.cache_miss_ratio.append(round(sess.cache_creation / total, 3))


def _pct(values, q):
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * q))]


def summary(pat, n_sessions):
    """JSON-ready view; hashes and counts only."""
    waits = {k: (int(pat.tool_wait_s[k]), pat.tool_wait_n[k], round(pat.tool_wait_s[k] / pat.tool_wait_n[k], 1))
             for k, _ in pat.tool_wait_s.most_common(20)}
    return {
        "reverts": pat.reverts.most_common(), "dangerous_forms": pat.dangerous.most_common(),
        "credential_reads": pat.credential_reads,
        "premature_sessions": pat.premature_sessions, "premature_share": round(pat.premature_sessions / n_sessions, 3) if n_sessions else 0,
        "churn_files_over_5_edits": pat.churn_files, "repeated_bash": pat.repeated_bash,
        "duplicate_reads": pat.duplicate_reads, "duplicate_read_chars": pat.duplicate_read_chars,
        "oversized_results_over_20k": pat.oversized_results.most_common(),
        "tool_wait_seconds_total_n_mean": waits,
        "nudge_prompts": pat.nudges, "near_duplicate_prompts": cluster_rows(pat.near_prompts),
        "done_claims": pat.done_claims, "done_without_verify": pat.done_without_verify,
        "interrupt_before_tool": pat.interrupt_before.most_common(10), "orphaned_agents": pat.orphaned_agents,
        "cache_miss_ratio_median": _pct(pat.cache_miss_ratio, 0.5), "cache_miss_ratio_p90": _pct(pat.cache_miss_ratio, 0.9),
    }
