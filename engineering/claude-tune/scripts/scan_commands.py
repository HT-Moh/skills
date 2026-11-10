"""Reduce shell commands to shapes that carry no argument values.

`prefix` yields `tool verb` for known tools and the bare tool name otherwise; `hook_key`
yields a hook script's basename. Both stop before any word that could be content.
"""
import os
import re
import shlex

KNOWN_TOOLS = ("git", "gh", "kubectl", "docker", "npm", "uv", "rtk", "make", "bun")  # tools whose next word is a verb, not content
TOOL_SHAPE_RE = re.compile(r"[\w.+-]{1,40}")
VERB_SHAPE_RE = re.compile(r"[a-z][a-z-]{1,20}")
SCRIPT_SHAPE_RE = re.compile(r"[\w./-]+\.(?:js|mjs|cjs|py|sh|ts)")
ASSIGNMENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*", re.S)
SEPARATORS = ("&&", "||", ";", "|", "&", "|&")
INLINE_CODE_FLAGS = ("-c", "-e", "--eval", "-p", "--print")
INTERPRETERS = ("node", "python3", "python", "bash", "sh", "uv", "npx", "bun")


def tokens(cmd):
    """Shell-aware tokens; separators inside quotes stay inside their word. None when unparsable."""
    lexer = shlex.shlex(cmd, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        return None


def segments(cmd):
    """Simple commands split at shell separators, VAR= assignments dropped. None when unparsable."""
    words = tokens(cmd)
    if words is None:
        return None
    out, current = [], []
    for tok in words:
        if tok in SEPARATORS:
            out.append(current)
            current = []
        else:
            current.append(tok)
    out.append(current)
    return [[w for w in seg if not ASSIGNMENT_RE.fullmatch(w)] for seg in out]


def argv(cmd):
    """Tokens of the first simple command that is not `cd`. None when unparsable, [] when empty."""
    segs = segments(cmd)
    if segs is None:
        return None
    for words in segs:
        if words and words[0] != "cd":
            return words
    return []


def _subcommand(words):
    """The first verb-shaped word after the tool, skipping flags and short-flag values."""
    skip_next = False
    for w in words[1:]:
        if skip_next:
            skip_next = False
            continue
        if re.fullmatch(r"-[A-Za-z]", w):
            skip_next = True
            continue
        if w.startswith("--") and "=" not in w:
            return ""  # a long flag may take the next word; stop rather than guess
        if w.startswith("-"):
            continue
        return w if VERB_SHAPE_RE.fullmatch(w) else ""
    return ""


def tool_name(words):
    name = os.path.basename(words[0])
    return name if TOOL_SHAPE_RE.fullmatch(name) else "(odd)"


def prefix_of_words(words):
    """`tool verb` for known tools, the bare tool name otherwise; never an argument value."""
    if not words:
        return "(empty)"
    tool = tool_name(words)
    if tool in KNOWN_TOOLS:
        return f"{tool} {_subcommand(words)}".strip()
    return tool


def prefix(cmd):
    words = argv(cmd)
    if words is None:
        return "(unparsed)"
    return prefix_of_words(words)


def hook_key(command):
    """The hook script's basename for an interpreter, else the program; inline code yields the program."""
    words = argv(command)
    if not words:
        return "(empty)" if words is not None else "(unparsed)"
    tool = tool_name(words)
    if tool in INTERPRETERS and not any(w in INLINE_CODE_FLAGS for w in words[1:]):
        script = next((w for w in words[1:] if SCRIPT_SHAPE_RE.fullmatch(w)), "")
        return os.path.basename(script) if script else tool
    return tool
