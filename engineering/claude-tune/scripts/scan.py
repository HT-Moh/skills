#!/usr/bin/env python3
"""Stream Claude Code transcripts and emit the measurements the tuning audit needs.

Read-only. Standard library only. Never prints message bodies or secret values.
Usage: scan.py --days 30 [--projects a,b] [--out summary.json] [--max-mb 800]
"""
import argparse, collections, datetime as dt, glob, json, os, re, sys, time

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, ".claude", "projects")
SIG = {
    "interrupts": "[Request interrupted by user",
    "classifier_denials": "denied by the Claude Code auto mode classifier",
    "hook_blocks": "hook_blocking_error",
    "edit_before_read": "File has not been read yet",
    "invalid_request_body": "Invalid request body",
}
REASON_RE = re.compile(r"classifier\. Reason: \[([^\]\\]{1,60})\]")
HOOK_RE = re.compile(r'"command":\s*"([^"]{0,160})"')
SECRET_RE = re.compile(r"sk_live_|rk_live_|Authorization: Bearer |BEGIN (RSA|OPENSSH) PRIVATE KEY")
WAIT_RE = re.compile(r"\b(sleep \d|until \[|until \$\(|watch )")


def ts(s):
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def prefix(cmd):
    cmd = cmd.strip()
    for _ in range(3):  # strip leading cd / export / VAR= segments
        cmd = re.sub(r"^((cd|export) [^&;|]+ *(&&|;) *)", "", cmd)
        cmd = re.sub(r"^([A-Za-z_][A-Za-z0-9_]*=\S+ *(&&|;)? *)+", "", cmd)
    cmd = re.sub(r"^/\S*/", "", cmd)  # /usr/bin/git -> git, /tmp/.../script.sh -> script.sh
    return " ".join(cmd.split()[:2])[:40] or "(empty)"


def is_boilerplate(text):
    t = text.lstrip()
    return t.lower().startswith((
        "<system", "[system", "<task-notification", "[request interrupted",
        "another claude session sent", "this session is being continued", "base directory for this skill",
        "<command-name>", "<local-command", "caveat: the messages below"))


class Pop:  # one population: interactive, headless, subagent
    def __init__(self):
        self.sessions = set(); self.user_msgs = 0; self.fresh = 0; self.cache_read = 0
        self.by_model = collections.Counter(); self.first_req = []
        self.tools = collections.Counter(); self.skills = collections.Counter()
        self.agents = collections.Counter(); self.sig = collections.Counter()
        self.reasons = collections.Counter(); self.hooks = collections.Counter()
        self.compactions = 0; self.pre_tokens = []; self.waits = 0
        self.bash_time = collections.Counter(); self.bash_n = collections.Counter()
        self.long_bash = 0; self.errors = 0; self.secret_hits = 0
        self.prompts = collections.defaultdict(set); self.msg_ids = set()


def scan_file(path, pop_for, max_bytes):
    size = os.path.getsize(path)
    if size > max_bytes:
        return "skipped"
    pending = {}  # tool_use id -> (ts, cmd)
    first_seen = False
    sess = os.path.basename(path)
    # The entrypoint field sits on the first user event, after its content; a long
    # pipeline prompt pushes it past 40 KB, so read generously. The first lines
    # (last-prompt, mode, permission-mode) do not carry it.
    with open(path, "rb") as fh:
        head = fh.read(400000).decode("utf-8", errors="replace")
    m = re.search(r'"entrypoint":"([^"]*)"', head)
    pop = pop_for(m.group(1) if m else "", path)
    pop.sessions.add(sess)
    with open(path, "r", errors="replace") as fh:
        for raw in fh:
            for k, needle in SIG.items():
                if needle in raw and pop is not None:
                    pop.sig[k] += 1
                    if k == "classifier_denials":
                        m = REASON_RE.search(raw)
                        if m: pop.reasons[m.group(1)] += 1
                    if k == "hook_blocks":
                        m = HOOK_RE.search(raw)
                        if m: pop.hooks[m.group(1).split("/")[-1][:60]] += 1
            if SECRET_RE.search(raw) and pop is not None:
                pop.secret_hits += 1
            try:
                ev = json.loads(raw)
            except Exception:
                continue
            t = ev.get("type"); msg = ev.get("message") or {}
            when = ts(ev.get("timestamp", "")) if ev.get("timestamp") else None
            if t == "system" and ev.get("subtype") == "compact_boundary":
                pop.compactions += 1
                pre = (ev.get("compactMetadata") or {}).get("preTokens")
                if pre: pop.pre_tokens.append(pre)
            content = msg.get("content")
            if t == "user":
                if isinstance(content, str) and content.strip():
                    pop.user_msgs += 1
                    if not is_boilerplate(content):
                        pop.prompts[" ".join(content.lower().split())[:60]].add(sess)
                elif isinstance(content, list):
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "tool_result":
                            if b.get("is_error"): pop.errors += 1
                            tid = b.get("tool_use_id")
                            if tid in pending and when:
                                t0, cmd = pending.pop(tid)
                                d = when - t0
                                p = prefix(cmd); pop.bash_time[p] += d; pop.bash_n[p] += 1
                                if d > 120: pop.long_bash += 1
                        elif isinstance(b, dict) and b.get("type") == "text":
                            pop.user_msgs += 1
                            if not is_boilerplate(b.get("text", "")):
                                pop.prompts[" ".join(b.get("text", "").lower().split())[:60]].add(sess)
            elif t == "assistant":
                u = msg.get("usage") or {}; mid = msg.get("id")
                if u and mid not in pop.msg_ids:
                    pop.msg_ids.add(mid)
                    fresh = (u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("output_tokens", 0))
                    pop.fresh += fresh; pop.cache_read += u.get("cache_read_input_tokens", 0)
                    pop.by_model[msg.get("model", "?")] += 1
                    if not first_seen:
                        first_seen = True
                        pop.first_req.append(u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0))
                if isinstance(content, list):
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "tool_use":
                            name = b.get("name", "?"); inp = b.get("input") or {}
                            pop.tools[name] += 1
                            if name == "Skill": pop.skills[str(inp.get("skill", "?"))] += 1
                            if name == "Agent": pop.agents[str(inp.get("subagent_type", "general-purpose"))] += 1
                            if name == "Bash":
                                cmd = str(inp.get("command", ""))
                                if WAIT_RE.search(cmd): pop.waits += 1
                                if when: pending[b.get("id")] = (when, cmd)
    return "ok"


def pct(v, q):
    if not v: return 0
    v = sorted(v); return v[min(len(v) - 1, int(len(v) * q))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30); ap.add_argument("--projects", default="")
    ap.add_argument("--out", default=""); ap.add_argument("--max-mb", type=int, default=800)
    a = ap.parse_args()
    cutoff = time.time() - a.days * 86400
    want = [p for p in a.projects.split(",") if p]
    pops = {"interactive": Pop(), "headless": Pop(), "subagent": Pop()}
    agent_types = collections.Counter()

    def pop_for(entrypoint, path):
        if "/subagents/" in path: return pops["subagent"]
        return pops["interactive"] if entrypoint in ("cli", "") else pops["headless"]

    files = []
    for proj in sorted(glob.glob(os.path.join(ROOT, "*"))):
        if want and not any(w in proj for w in want): continue
        for f in glob.glob(os.path.join(proj, "*.jsonl")) + glob.glob(os.path.join(proj, "*", "subagents", "agent-*.jsonl")):
            if os.path.getmtime(f) >= cutoff: files.append(f)
    for f in glob.glob(os.path.join(ROOT, "*", "*", "subagents", "agent-*.meta.json")):
        if os.path.getmtime(f) >= cutoff:
            try: agent_types[json.load(open(f)).get("agentType", "?")] += 1
            except Exception: pass
    skipped = 0; t0 = time.time()
    for i, f in enumerate(files):
        if scan_file(f, pop_for, a.max_mb * 1048576) == "skipped": skipped += 1
        if i % 200 == 0: print(f"  scanned {i}/{len(files)} files, {int(time.time()-t0)}s", file=sys.stderr)

    out = {"days": a.days, "files": len(files), "skipped_over_max_mb": skipped, "subagent_types_from_meta": agent_types.most_common(25)}
    for name, p in pops.items():
        repeated = sorted(((len(s), k) for k, s in p.prompts.items() if len(s) >= 3 and len(k) > 3), reverse=True)[:15]
        out[name] = {
            "sessions": len(p.sessions), "user_messages": p.user_msgs,
            "fresh_tokens_M": round(p.fresh / 1e6, 1), "cache_read_tokens_M": round(p.cache_read / 1e6, 1),
            "by_model": p.by_model.most_common(6),
            "first_request_tokens_median": pct(p.first_req, 0.5), "first_request_tokens_p90": pct(p.first_req, 0.9),
            "compactions": p.compactions, "compaction_pre_tokens_median": pct(p.pre_tokens, 0.5), "compactions_near_1M": sum(1 for x in p.pre_tokens if x > 900000),
            "signals": dict(p.sig), "denial_reasons": p.reasons.most_common(10), "blocking_hooks": p.hooks.most_common(8),
            "tool_errors": p.errors, "secret_pattern_lines": p.secret_hits,
            "tools": p.tools.most_common(15), "skills": p.skills.most_common(20), "agents_spawned": p.agents.most_common(20),
            "bash_wait_commands": p.waits, "bash_over_120s": p.long_bash,
            "bash_top_by_seconds": [(k, int(v), p.bash_n[k]) for k, v in p.bash_time.most_common(12)],
            "repeated_prompts_sessions": [(n, k) for n, k in repeated],
        }
    txt = json.dumps(out, indent=1)
    if a.out:
        with open(a.out, "w") as fh: fh.write(txt)
        print(f"written {a.out}", file=sys.stderr)
    for name in pops:
        d = out[name]
        print(f"== {name}: sessions={d['sessions']} user_msgs={d['user_messages']} fresh={d['fresh_tokens_M']}M cache_read={d['cache_read_tokens_M']}M first_req_med={d['first_request_tokens_median']} compactions={d['compactions']} (near1M={d['compactions_near_1M']})")
        print(f"   signals={d['signals']} errors={d['tool_errors']} waits={d['bash_wait_commands']} bash>120s={d['bash_over_120s']} secret_lines={d['secret_pattern_lines']}")
        print(f"   denials={d['denial_reasons'][:5]}")
        print(f"   agents={d['agents_spawned'][:8]}")
        print(f"   skills={d['skills'][:8]}")
        print(f"   slow_bash={d['bash_top_by_seconds'][:5]}")
        print(f"   repeated={d['repeated_prompts_sessions'][:5]}")
    print(f"== subagent types (meta): {out['subagent_types_from_meta'][:12]}")
    print(f"== files={out['files']} skipped_over_max_mb={skipped}")


if __name__ == "__main__":
    main()
