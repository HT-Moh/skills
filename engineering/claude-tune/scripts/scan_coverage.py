"""Skill and MCP coverage: what was installed versus what each session invoked.

Fed from `inventory.json` (written by `skill_inventory.py`). Each distinct prompt is scored
against every model-invoked skill by the distinct trigger terms it contains; the threshold grows
with prompt length and only the two best skills per prompt survive. A skill matched by two
prompts of a session, or by one short prompt, and never invoked there is a missed skill. Only
skill names, server names, transcript paths and line numbers leave this module: no prompt text.
"""
import collections
import json
import os
import re
import sys

import scan_patterns

PROJECTS_ROOT = os.path.join(os.path.expanduser("~"), ".claude", "projects")
MIN_PROMPT_CHARS = 40
SHORT_PROMPT_CHARS = 300  # a short prompt that names the task is a strong signal on its own
CANDIDATE_SCORE = 3
CHARS_PER_EXTRA_TERM = 600  # a 1200-char prompt needs 5 distinct terms
BEST_PER_PROMPT = 2
PHRASE_WEIGHT = 2
MAX_LOCATIONS = 5
TOP_MISSED = 15
WORD_RE = re.compile(r"[a-z0-9][a-z0-9'-]*")


def bare_skill_name(name):
    """`plugin:skill` and `skill` both become `skill`."""
    return str(name).split(":")[-1]


def mcp_server_of(tool_name):
    """`mcp__<server>__<tool>` gives `<server>`; anything else gives None."""
    if not tool_name.startswith("mcp__"):
        return None
    parts = tool_name.split("__")
    return parts[1] if len(parts) >= 3 and parts[1] else None


def project_location(path):
    """The transcript path relative to `~/.claude/projects` with the project dir hashed:
    `<path_key(project-dir)>/<file>` or `<hash>/<session>/subagents/<file>`.

    The project dir is hashed because a long UUID-bearing dir name trips the secret filter
    that guards the summary; `resolve_project_dir` maps the hash back for the reader.
    """
    parts = path.replace("\\", "/").split("/")
    start = parts.index("projects") + 1 if "projects" in parts and parts.index("projects") + 1 < len(parts) - 1 else max(len(parts) - 2, 0)
    return "/".join([scan_patterns.path_key(parts[start])] + parts[start + 1:])


def resolve_project_dir(digest, root):
    """The directory name under `root` whose `path_key` is `digest`, or '' when none matches."""
    try:
        names = os.listdir(root)
    except OSError:
        return ""
    return next((n for n in sorted(names) if scan_patterns.path_key(n) == digest), "")


class Index:
    """Inventory reduced to what scoring needs: per skill, word terms and phrase terms."""

    def __init__(self, inventory):
        self.skills = {}
        for row in inventory.get("skills") or []:
            if not row.get("model_invoked", True):
                continue
            terms = [str(t).lower() for t in row.get("terms") or []]
            phrases = tuple(t for t in terms if " " in t)
            words = frozenset(t for t in terms if " " not in t)
            self.skills[bare_skill_name(row["name"])] = (words, phrases)
        self.mcp_names = sorted({s["name"] for s in inventory.get("mcp_servers") or []})
        self.n_skills = len(inventory.get("skills") or [])

    @classmethod
    def from_file(cls, path):
        with open(path, encoding="utf-8") as fh:
            return cls(json.load(fh))


def score(lower_text, words, skill_terms):
    word_terms, phrase_terms = skill_terms
    return len(word_terms & words) + PHRASE_WEIGHT * sum(1 for p in phrase_terms if p in lower_text)


def prompt_identity(text):
    """Same normalisation as `scan_lib.prompt_key`: lower-cased, whitespace collapsed. In-memory only."""
    return " ".join(text.lower().split())


def best_matches(index, text):
    """Skills whose score reaches the length-scaled threshold, cut to the two best scores (ties kept)."""
    lower = text.lower()
    words = frozenset(WORD_RE.findall(lower))
    threshold = CANDIDATE_SCORE + len(text.strip()) // CHARS_PER_EXTRA_TERM
    scored = sorted(((score(lower, words, terms), skill) for skill, terms in index.skills.items()), reverse=True)
    kept = [(s, skill) for s, skill in scored if s >= threshold]
    if len(kept) <= BEST_PER_PROMPT:
        return [skill for _, skill in kept]
    cutoff = kept[BEST_PER_PROMPT - 1][0]
    return [skill for s, skill in kept if s >= cutoff]


class Match:
    """What one session saw of one skill: how many distinct prompts matched, the first line, a short one."""

    def __init__(self, line, short):
        self.prompts = 1
        self.line = line
        self.short = short

    def is_candidate(self):
        return self.prompts >= 2 or self.short


class Coverage:
    """Population-level counters plus the state of the session being streamed."""

    def __init__(self, index=None):
        self.index = index
        self.missed = collections.Counter()
        self.missed_locations = collections.defaultdict(list)
        self.mcp_used = collections.Counter()
        self.skills_used = set()
        self.line = 0
        self._location = ""
        self._invoked = set()
        self._matches = {}
        self._seen_prompts = set()

    def begin_session(self, path):
        self.line = 0
        self._location = project_location(path)
        self._invoked = set()
        self._matches = {}
        self._seen_prompts = set()

    def on_prompt(self, text, line=None):
        """Score one non-boilerplate user prompt once per distinct text; keep the first matching line per skill.

        `line` defaults to `self.line`, which the streaming loop sets before each event.
        """
        if self.index is None or len(text.strip()) < MIN_PROMPT_CHARS:
            return
        identity = prompt_identity(text)
        if identity in self._seen_prompts:
            return
        self._seen_prompts.add(identity)
        short = len(text.strip()) < SHORT_PROMPT_CHARS
        line = self.line if line is None else line
        for skill in best_matches(self.index, text):
            if skill in self._matches:
                self._matches[skill].prompts += 1
                self._matches[skill].short |= short
            else:
                self._matches[skill] = Match(line, short)

    def on_tool_use(self, name, inp):
        if name == "Skill":
            self._invoked.add(bare_skill_name((inp or {}).get("skill", "?")))
        elif (server := mcp_server_of(name)) is not None:
            self.mcp_used[server] += 1

    def end_session(self):
        self.skills_used |= self._invoked
        for skill, match in self._matches.items():
            if skill in self._invoked or not match.is_candidate():
                continue
            self.missed[skill] += 1
            if len(self.missed_locations[skill]) < MAX_LOCATIONS:
                self.missed_locations[skill].append([self._location, match.line])
        self._matches = {}


def summary(cov):
    """Six population-level keys; all empty when the scan ran without an inventory."""
    if cov.index is None:
        return {"skills_available": 0, "skills_used_distinct": 0, "missed_skill_sessions": [],
                "mcp_servers_configured": [], "mcp_servers_used": {}, "mcp_servers_unused": []}
    missed = [{"skill": skill, "sessions": n, "locations": cov.missed_locations[skill]}
              for skill, n in cov.missed.most_common(TOP_MISSED)]
    used = dict(cov.mcp_used.most_common())
    return {
        "skills_available": cov.index.n_skills, "skills_used_distinct": len(cov.skills_used),
        "missed_skill_sessions": missed, "mcp_servers_configured": cov.index.mcp_names,
        "mcp_servers_used": used, "mcp_servers_unused": [n for n in cov.index.mcp_names if n not in used],
    }


if __name__ == "__main__":
    # `scan_coverage.py --resolve <hash>` prints the project dir a location's hash stands for.
    if len(sys.argv) == 3 and sys.argv[1] == "--resolve":
        print(resolve_project_dir(sys.argv[2], PROJECTS_ROOT) or f"no project dir hashes to {sys.argv[2]}")
    else:
        print("usage: scan_coverage.py --resolve <12-char hash from a missed_skill_sessions location>")
