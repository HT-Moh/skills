"""Skill and MCP coverage: what was installed versus what each session invoked.

Fed from `inventory.json` (written by `skill_inventory.py`). A prompt is scored against every
model-invoked skill by the distinct trigger terms it contains; a skill that scores high in a
session and is never invoked there is a missed skill. Only skill names, server names, file
basenames and line numbers leave this module: no prompt text.
"""
import collections
import json
import re

MIN_PROMPT_CHARS = 40
CANDIDATE_SCORE = 3
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
    """The transcript path relative to `~/.claude/projects`: `<project-dir>/<file>`, or
    `<project-dir>/<session>/subagents/<file>` for a subagent transcript."""
    parts = path.replace("\\", "/").split("/")
    if "projects" in parts and parts.index("projects") + 1 < len(parts) - 1:
        return "/".join(parts[parts.index("projects") + 1:])
    return "/".join(parts[-2:]) if len(parts) >= 2 else parts[-1]


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
        self._candidates = {}

    def begin_session(self, path):
        self.line = 0
        self._location = project_location(path)
        self._invoked = set()
        self._candidates = {}

    def on_prompt(self, text, line=None):
        """Score one non-boilerplate user prompt; remember the first matching line per skill.

        `line` defaults to `self.line`, which the streaming loop sets before each event.
        """
        if self.index is None or len(text.strip()) < MIN_PROMPT_CHARS:
            return
        lower = text.lower()
        words = frozenset(WORD_RE.findall(lower))
        line = self.line if line is None else line
        for skill, terms in self.index.skills.items():
            if skill not in self._candidates and score(lower, words, terms) >= CANDIDATE_SCORE:
                self._candidates[skill] = line

    def on_tool_use(self, name, inp):
        if name == "Skill":
            self._invoked.add(bare_skill_name((inp or {}).get("skill", "?")))
        elif (server := mcp_server_of(name)) is not None:
            self.mcp_used[server] += 1

    def end_session(self):
        self.skills_used |= self._invoked
        for skill, line in self._candidates.items():
            if skill in self._invoked:
                continue
            self.missed[skill] += 1
            if len(self.missed_locations[skill]) < MAX_LOCATIONS:
                self.missed_locations[skill].append([self._location, line])
        self._candidates = {}


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
