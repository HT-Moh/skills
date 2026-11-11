"""Recurring tool sequences: 3-grams of consecutive tool tokens, counted by distinct session.

A tool call is reduced to a token that carries no argument: `Bash:<prefix>` through
`scan_commands.prefix`, `Skill:<skill>`, `Agent:<subagent_type>`, otherwise the tool name.
A 3-gram seen in three or more sessions is a workflow the user runs by hand; brief B turns
it into a skill candidate.
"""
import collections

import scan_commands

NGRAM = 3
MIN_SESSIONS = 3
ROWS_KEPT = 15
JOINER = " > "


def token_of(name, inp):
    if name == "Bash":
        return f"Bash:{scan_commands.prefix(str(inp.get('command', '')))}"
    if name == "Skill":
        return f"Skill:{inp.get('skill', '?')}"
    if name == "Agent":
        return f"Agent:{inp.get('subagent_type', 'general-purpose')}"
    return name


def new_window():
    """Per-session memory: only the last NGRAM tokens are kept."""
    return collections.deque(maxlen=NGRAM)


def record(token, window, session_name, sequences):
    """Push one token; when the window is full and not one tool repeated, note the 3-gram for this session."""
    window.append(token)
    if len(window) < NGRAM or len(set(window)) == 1:
        return
    sequences[JOINER.join(window)].add(session_name)


def rows(sequences):
    """Top 15 `{sequence, sessions}` with 3+ sessions, most sessions first."""
    kept = sorted(((len(s), seq) for seq, s in sequences.items() if len(s) >= MIN_SESSIONS), key=lambda t: (-t[0], t[1]))
    return [{"sequence": seq, "sessions": n} for n, seq in kept[:ROWS_KEPT]]
