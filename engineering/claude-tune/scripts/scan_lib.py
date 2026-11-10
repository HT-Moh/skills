"""Streaming measurements over Claude Code transcripts, without ever emitting content.

Commands are reduced to a tool name plus a known subcommand, hooks to a basename, prompts
to a hash and a length. The summary is written owner-only and refused if it still carries
anything credential-shaped.
"""
import collections
import datetime as dt
import hashlib
import json
import os
import re
import shlex
import sys

APPLY_SCRIPTS = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "claude-tune-apply", "scripts")
sys.path.insert(0, os.path.realpath(APPLY_SCRIPTS))
from redact import has_secret  # noqa: E402

SIG = {
    "interrupts": "[Request interrupted by user",
    "classifier_denials": "denied by the Claude Code auto mode classifier",
    "hook_blocks": "hook_blocking_error",
    "edit_before_read": "File has not been read yet",
    "invalid_request_body": "Invalid request body",
}
REASON_RE = re.compile(r"classifier\. Reason: \[([^\]\\]{1,60})\]")
HOOK_RE = re.compile(r'"command":\s*"([^"]{0,160})"')
SECRET_HINT_RE = re.compile(r"sk_live_|rk_live_|Authorization: Bearer |BEGIN (RSA|OPENSSH) PRIVATE KEY")
WAIT_RE = re.compile(r"\b(sleep \d|until \[|until \$\(|watch )")
KNOWN_TOOLS = ("git", "gh", "kubectl", "docker", "npm", "uv", "rtk", "make", "bun")  # tools whose next word is a verb, not content
LONG_BASH_S = 120
BOILERPLATE_PREFIXES = ("<system", "[system", "<task-notification", "[request interrupted", "another claude session sent",
                        "this session is being continued", "base directory for this skill", "<command-name>",
                        "<local-command", "caveat: the messages below")


def ts(s):
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _argv(cmd):
    """Tokens of the first simple command, after leading cd/export/VAR= segments."""
    first = re.split(r"\s*(?:&&|\|\||;|\|)\s*", cmd.strip(), maxsplit=8)
    for segment in first:
        try:
            words = shlex.split(segment)
        except ValueError:
            words = segment.split()
        words = [w for w in words if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", w)]
        if words and words[0] != "cd":
            return words  # a bare `export` segment stays as the tool name; its value is gone
    return []


def _subcommand(words):
    """First word that is neither a flag, a short flag's value, nor a path."""
    skip_next = False
    for w in words[1:]:
        if skip_next:
            skip_next = False
            continue
        if re.fullmatch(r"-[A-Za-z]", w):
            skip_next = True
            continue
        if w.startswith("-") or re.fullmatch(r"[\w./-]*/[\w./-]*", w):
            continue
        return w
    return ""


def prefix(cmd):
    """`tool subcommand` for known tools, the bare tool name otherwise; never an argument value."""
    words = _argv(cmd)
    if not words:
        return "(empty)"
    tool = os.path.basename(words[0])
    if tool in KNOWN_TOOLS:
        return f"{tool} {_subcommand(words)}".strip()
    return tool


INTERPRETERS = ("node", "python3", "python", "bash", "sh", "uv", "npx", "bun")


def hook_key(command):
    """The hook script's basename, or the program when no script follows."""
    words = _argv(command)
    if not words:
        return "(empty)"
    tool = os.path.basename(words[0])
    if tool in INTERPRETERS:
        script = next((w for w in words[1:] if not w.startswith("-")), "")
        return os.path.basename(script) if script else tool
    return tool


def prompt_key(text):
    """A hash of the prompt plus its length: enough to count repeats, nothing to read."""
    normalized = " ".join(text.lower().split())
    return f"{hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:12]}:{len(normalized)}"


def is_boilerplate(text):
    return text.lstrip().lower().startswith(BOILERPLATE_PREFIXES)


class Pop:
    """One population: interactive, headless or subagent."""

    def __init__(self):
        self.sessions = set(); self.user_msgs = 0; self.fresh = 0; self.cache_read = 0
        self.by_model = collections.Counter(); self.first_req = []
        self.tools = collections.Counter(); self.skills = collections.Counter()
        self.agents = collections.Counter(); self.sig = collections.Counter()
        self.reasons = collections.Counter(); self.hooks = collections.Counter()
        self.compactions = 0; self.pre_tokens = []; self.waits = 0
        self.bash_time = collections.Counter(); self.bash_n = collections.Counter()
        self.long_bash = 0; self.errors = 0; self.secret_hits = 0; self.malformed = 0
        self.prompts = collections.defaultdict(set); self.msg_ids = set()


def classify_line(raw, pop):
    """Count signal strings on the raw line before it is parsed."""
    for key, needle in SIG.items():
        if needle not in raw:
            continue
        pop.sig[key] += 1
        if key == "classifier_denials" and (m := REASON_RE.search(raw)):
            pop.reasons[m.group(1)] += 1
        if key == "hook_blocks" and (m := HOOK_RE.search(raw)):
            pop.hooks[hook_key(m.group(1))] += 1
    if SECRET_HINT_RE.search(raw):
        pop.secret_hits += 1


def _entrypoint(path):
    with open(path, "rb") as fh:
        head = fh.read(400000).decode("utf-8", errors="replace")
    m = re.search(r'"entrypoint":"([^"]*)"', head)
    return m.group(1) if m else ""


def record_user(ev, pop, pending, when, sess):
    content = (ev.get("message") or {}).get("content")
    blocks = [content] if isinstance(content, str) else (content if isinstance(content, list) else [])
    for b in blocks:
        text = b if isinstance(b, str) else (b.get("text", "") if isinstance(b, dict) and b.get("type") == "text" else None)
        if isinstance(b, dict) and b.get("type") == "tool_result":
            _record_tool_result(b, pop, pending, when)
        elif text is not None and text.strip():
            pop.user_msgs += 1
            if not is_boilerplate(text):
                pop.prompts[prompt_key(text)].add(sess)


def _record_tool_result(block, pop, pending, when):
    if block.get("is_error"):
        pop.errors += 1
    tid = block.get("tool_use_id")
    if tid in pending and when:
        t0, cmd = pending.pop(tid)
        p = prefix(cmd)
        pop.bash_time[p] += when - t0
        pop.bash_n[p] += 1
        if when - t0 > LONG_BASH_S:
            pop.long_bash += 1


def record_assistant(ev, pop, pending, when, first_seen):
    """Usage once per message id, then every tool_use block. Returns the new first_seen flag."""
    msg = ev.get("message") or {}
    usage = msg.get("usage") or {}
    mid = msg.get("id")
    if usage and (mid is None or mid not in pop.msg_ids):
        pop.msg_ids.add(mid)
        pop.fresh += usage.get("input_tokens", 0) + usage.get("cache_creation_input_tokens", 0) + usage.get("output_tokens", 0)
        pop.cache_read += usage.get("cache_read_input_tokens", 0)
        pop.by_model[msg.get("model", "?")] += 1
        if not first_seen:
            first_seen = True
            pop.first_req.append(usage.get("input_tokens", 0) + usage.get("cache_creation_input_tokens", 0) + usage.get("cache_read_input_tokens", 0))
    for b in msg.get("content") if isinstance(msg.get("content"), list) else []:
        if isinstance(b, dict) and b.get("type") == "tool_use":
            _record_tool_use(b, pop, pending, when)
    return first_seen


def _record_tool_use(block, pop, pending, when):
    name = block.get("name", "?")
    inp = block.get("input") or {}
    pop.tools[name] += 1
    if name == "Skill":
        pop.skills[str(inp.get("skill", "?"))] += 1
    if name == "Agent":
        pop.agents[str(inp.get("subagent_type", "general-purpose"))] += 1
    if name == "Bash":
        cmd = str(inp.get("command", ""))
        if WAIT_RE.search(cmd):
            pop.waits += 1
        if when:
            pending[block.get("id")] = (when, cmd)


def _record_compaction(ev, pop):
    pop.compactions += 1
    pre = (ev.get("compactMetadata") or {}).get("preTokens")
    if pre:
        pop.pre_tokens.append(pre)


def scan_file(path, pop_for, max_bytes, cutoff=0.0):
    """Stream one transcript into its population; events older than `cutoff` are skipped."""
    if os.path.getsize(path) > max_bytes:
        return "skipped"
    pop = pop_for(_entrypoint(path), path)
    sess = os.path.basename(path)
    pop.sessions.add(sess)
    pending, first_seen = {}, False
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            classify_line(raw, pop)
            ev = _parse(raw, pop)
            if ev is None:
                continue
            when = ts(ev.get("timestamp", "")) if ev.get("timestamp") else None
            if when is not None and when < cutoff:
                continue
            first_seen = _dispatch(ev, pop, pending, when, sess, first_seen)
    return "ok"


def _parse(raw, pop):
    try:
        ev = json.loads(raw)
    except ValueError:
        pop.malformed += 1
        return None
    if not isinstance(ev, dict) or not isinstance(ev.get("message", {}), dict):
        pop.malformed += 1
        return None
    return ev


def _dispatch(ev, pop, pending, when, sess, first_seen):
    kind = ev.get("type")
    if kind == "system" and ev.get("subtype") == "compact_boundary":
        _record_compaction(ev, pop)
    elif kind == "user":
        record_user(ev, pop, pending, when, sess)
    elif kind == "assistant":
        return record_assistant(ev, pop, pending, when, first_seen)
    return first_seen


def write_summary(out, path):
    """Owner-only JSON; refuses when any value still looks like a credential."""
    text = json.dumps(out, indent=1)
    if has_secret(text):
        raise ValueError("summary contains a secret-shaped value; not written")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
