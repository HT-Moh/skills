#!/usr/bin/env python3
"""Stream Claude Code transcripts and emit the measurements the tuning audit needs.

Read-only. Standard library only. Prints no message bodies, no command arguments and no
prompt text: commands become `tool subcommand`, prompts become a hash and a length.
Usage: scan.py --days 30 [--projects a,b] [--out summary.json] [--max-mb 800]
"""
import argparse
import collections
import glob
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import scan_lib  # noqa: E402

ROOT = os.path.join(os.path.expanduser("~"), ".claude", "projects")


def pct(values, q):
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * q))]


def find_files(want, cutoff):
    files = []
    for proj in sorted(glob.glob(os.path.join(ROOT, "*"))):
        if want and not any(w in proj for w in want):
            continue
        for f in glob.glob(os.path.join(proj, "*.jsonl")) + glob.glob(os.path.join(proj, "*", "subagents", "agent-*.jsonl")):
            if os.path.getmtime(f) >= cutoff:
                files.append(f)
    return files


def agent_types_from_meta(want, cutoff):
    counts = collections.Counter()
    for f in glob.glob(os.path.join(ROOT, "*", "*", "subagents", "agent-*.meta.json")):
        if want and not any(w in f for w in want):
            continue
        if os.path.getmtime(f) < cutoff:
            continue
        try:
            with open(f, encoding="utf-8") as fh:
                counts[json.load(fh).get("agentType", "?")] += 1
        except (OSError, ValueError):
            pass
    return counts.most_common(25)


def population_summary(p):
    repeated = sorted(((len(s), k) for k, s in p.prompts.items() if len(s) >= 3), reverse=True)[:15]
    return {
        "sessions": len(p.sessions), "user_messages": p.user_msgs,
        "fresh_tokens_M": round(p.fresh / 1e6, 1), "cache_read_tokens_M": round(p.cache_read / 1e6, 1),
        "by_model": p.by_model.most_common(6),
        "first_request_tokens_median": pct(p.first_req, 0.5), "first_request_tokens_p90": pct(p.first_req, 0.9),
        "compactions": p.compactions, "compaction_pre_tokens_median": pct(p.pre_tokens, 0.5),
        "compactions_near_1M": sum(1 for x in p.pre_tokens if x > 900000),
        "signals": dict(p.sig), "denial_reasons": p.reasons.most_common(10), "blocking_hooks": p.hooks.most_common(8),
        "tool_errors": p.errors, "secret_pattern_lines": p.secret_hits, "malformed_lines": p.malformed,
        "tools": p.tools.most_common(15), "skills": p.skills.most_common(20), "agents_spawned": p.agents.most_common(20),
        "bash_wait_commands": p.waits, "bash_over_120s": p.long_bash,
        "bash_top_by_seconds": [(k, int(v), p.bash_n[k]) for k, v in p.bash_time.most_common(12)],
        "repeated_prompts_sessions": [(n, k.split(":")[0], int(k.split(":")[1])) for n, k in repeated],
    }


def print_summary(out):
    for name in ("interactive", "headless", "subagent"):
        d = out[name]
        print(f"== {name}: sessions={d['sessions']} user_msgs={d['user_messages']} fresh={d['fresh_tokens_M']}M "
              f"cache_read={d['cache_read_tokens_M']}M first_req_med={d['first_request_tokens_median']} "
              f"compactions={d['compactions']} (near1M={d['compactions_near_1M']})")
        print(f"   signals={d['signals']} errors={d['tool_errors']} waits={d['bash_wait_commands']} "
              f"bash>120s={d['bash_over_120s']} secret_lines={d['secret_pattern_lines']} malformed={d['malformed_lines']}")
        print(f"   denials={d['denial_reasons'][:5]}")
        print(f"   agents={d['agents_spawned'][:8]}")
        print(f"   skills={d['skills'][:8]}")
        print(f"   slow_bash={d['bash_top_by_seconds'][:5]}")
        print(f"   repeated_prompts(hash,len)={d['repeated_prompts_sessions'][:5]}")
    print(f"== subagent types (meta): {out['subagent_types_from_meta'][:12]}")
    print(f"== files={out['files']} skipped_over_max_mb={out['skipped_over_max_mb']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--projects", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--max-mb", type=int, default=800)
    a = ap.parse_args()
    cutoff = time.time() - a.days * 86400
    want = [p for p in a.projects.split(",") if p]
    pops = {"interactive": scan_lib.Pop(), "headless": scan_lib.Pop(), "subagent": scan_lib.Pop()}

    def pop_for(entrypoint, path):
        if "/subagents/" in path:
            return pops["subagent"]
        return pops["interactive"] if entrypoint in ("cli", "") else pops["headless"]

    files = find_files(want, cutoff)
    skipped, t0 = 0, time.time()
    for i, f in enumerate(files):
        if scan_lib.scan_file(f, pop_for, a.max_mb * 1048576, cutoff) == "skipped":
            skipped += 1
        if i % 200 == 0:
            print(f"  scanned {i}/{len(files)} files, {int(time.time() - t0)}s", file=sys.stderr)
    out = {"days": a.days, "files": len(files), "skipped_over_max_mb": skipped,
           "subagent_types_from_meta": agent_types_from_meta(want, cutoff)}
    out.update({name: population_summary(p) for name, p in pops.items()})
    if a.out:
        scan_lib.write_summary(out, a.out)
        print(f"written {a.out}", file=sys.stderr)
    print_summary(out)


if __name__ == "__main__":
    main()
