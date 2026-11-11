#!/usr/bin/env python3
"""List what this machine's Claude Code could have used: skills, MCP server names, agents.

Read-only. Standard library only. Reads SKILL.md frontmatter, settings.json `enabledPlugins`
and `skillOverrides`, and the server NAMES in `~/.claude.json`, `.mcp.json` files and plugin
`.mcp.json` files. Never copies `env`, `headers`, `url` or any other server field into output.
Usage: skill_inventory.py --out inventory.json [--projects /repo/a,/repo/b]
"""
import argparse
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import scan_lib  # noqa: E402

MAX_TERMS = 40
MIN_TERM_CHARS = 4
STOPWORDS = frozenset("""
about above after again against also always among another anything around because been before being below
between both cannot claude code could does doing during each either every from further have having here
into itself just like mentions more most must need needs never only other ought over same should since
skill skills some such than that their them then there these they this those through under until upon
user users uses using very want wants were what when where whether which while will with within without
would your yours examples example include includes including trigger triggers triggered request requests
asks asking said says something someone anything everything nothing like likes also well many much
""".split())
PHRASE_RE = re.compile(r'"([^"]{3,60})"')
WORD_RE = re.compile(r"[a-z][a-z0-9'-]*")
FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---", re.S)
PLUGIN_ID_RE = re.compile(r"^(?P<plugin>[^@]+)@(?P<marketplace>.+)$")


def frontmatter(text):
    """Minimal YAML reader: `key: value`, quoted values, and `>-`/`|` folded blocks."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    out, key = {}, None
    for line in m.group(1).splitlines():
        if line.startswith((" ", "\t")) and key:
            out[key] = (out[key] + " " + line.strip()).strip()
            continue
        k, sep, v = line.partition(":")
        if not sep or " " in k.strip():
            continue
        key, v = k.strip(), v.strip()
        out[key] = "" if v in (">-", ">", "|", "|-") else v.strip("\"'")
    return out


def terms_of(description):
    """Quoted phrases first, then words of 4+ chars minus stopwords; deduped, capped."""
    lower = description.lower()
    phrases = [p.strip().lower() for p in PHRASE_RE.findall(description) if " " in p.strip()]
    words = [w for w in WORD_RE.findall(lower) if len(w) >= MIN_TERM_CHARS and w not in STOPWORDS]
    seen, out = set(), []
    for term in phrases + words:
        if term not in seen:
            seen.add(term)
            out.append(term)
    return out[:MAX_TERMS]


def skill_entry(skill_md, source, name, disabled_names):
    fm = frontmatter(_read(skill_md))
    description = fm.get("description", "")
    name = fm.get("name") or name
    model_invoked = fm.get("disable-model-invocation", "").lower() != "true" and name not in disabled_names
    return {"name": name, "source": source, "path": os.path.realpath(skill_md), "model_invoked": model_invoked,
            "description_chars": len(description), "terms": terms_of(description)}


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read(65536)
    except OSError:
        return ""


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            loaded = json.load(fh)
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def skills_under(skills_dir, source, disabled_names):
    """Every `<skills_dir>/*/SKILL.md`; symlinked skills keep the link name, one entry per real file."""
    rows, seen = [], set()
    for skill_md in sorted(glob.glob(os.path.join(skills_dir, "*", "SKILL.md"))):
        real = os.path.realpath(skill_md)
        if real in seen:
            continue
        seen.add(real)
        rows.append(skill_entry(skill_md, source, os.path.basename(os.path.dirname(skill_md)), disabled_names))
    return rows


def disabled_skill_names(settings):
    overrides = settings.get("skillOverrides") or {}
    if not isinstance(overrides, dict):
        return frozenset()
    return frozenset(name.split(":")[-1] for name, state in overrides.items() if state in ("off", False))


def enabled_plugins(settings):
    """(plugin, marketplace) for every `plugin@marketplace: true` in `enabledPlugins`."""
    enabled = settings.get("enabledPlugins") or {}
    out = []
    for plugin_id, state in enabled.items() if isinstance(enabled, dict) else []:
        m = PLUGIN_ID_RE.match(plugin_id)
        if state is True and m:
            out.append((m.group("plugin"), m.group("marketplace")))
    return out


def plugin_root(home, plugin, marketplace):
    """The installed version dir: `installed_plugins.json` `installPath`, else the newest version dir."""
    records = _load_json(os.path.join(home, ".claude", "plugins", "installed_plugins.json")).get("plugins") or {}
    for record in records.get(f"{plugin}@{marketplace}") or []:
        path = record.get("installPath") if isinstance(record, dict) else None
        if path and os.path.isdir(path):
            return path
    versions = glob.glob(os.path.join(home, ".claude", "plugins", "cache", marketplace, plugin, "*", ""))
    return max(versions, key=os.path.getmtime).rstrip(os.sep) if versions else ""


def agents_under(agents_dir, source):
    return [{"name": os.path.splitext(os.path.basename(p))[0], "source": source}
            for p in sorted(glob.glob(os.path.join(agents_dir, "*.md")))]


def mcp_names(config, source, prefix=""):
    """Server names from a parsed `{mcpServers: {...}}` object; values are never looked at."""
    servers = config.get("mcpServers") or {}
    return [{"name": prefix + name, "source": source} for name in sorted(servers)] if isinstance(servers, dict) else []


def plugin_components(home, settings, disabled_names):
    skills, agents, servers = [], [], []
    for plugin, marketplace in enabled_plugins(settings):
        root = plugin_root(home, plugin, marketplace)
        if not root:
            continue
        source = f"plugin:{plugin}"
        skills += skills_under(os.path.join(root, "skills"), source, disabled_names)
        agents += agents_under(os.path.join(root, "agents"), source)
        servers += mcp_names(_load_json(os.path.join(root, ".mcp.json")), source, prefix=f"plugin_{plugin}_")
    return skills, agents, servers


def project_components(projects, disabled_names, claude_json):
    skills, servers = [], []
    for repo in projects:
        skills += skills_under(os.path.join(repo, ".claude", "skills"), "project", disabled_names)
        servers += mcp_names(_load_json(os.path.join(repo, ".mcp.json")), "project")
        local = (claude_json.get("projects") or {}).get(repo) or {}
        servers += mcp_names(local if isinstance(local, dict) else {}, "project-local")
    return skills, servers


def build_inventory(home, projects):
    settings = _load_json(os.path.join(home, ".claude", "settings.json"))
    claude_json = _load_json(os.path.join(home, ".claude.json"))
    disabled = disabled_skill_names(settings)
    skills = skills_under(os.path.join(home, ".claude", "skills"), "user", disabled)
    agents = agents_under(os.path.join(home, ".claude", "agents"), "user")
    servers = mcp_names(claude_json, "user")
    plugin_skills, plugin_agents, plugin_servers = plugin_components(home, settings, disabled)
    project_skills, project_servers = project_components(projects, disabled, claude_json)
    skills += plugin_skills + project_skills
    servers += plugin_servers + project_servers
    agents += plugin_agents
    totals = {"skills": len(skills), "skills_model_invoked": sum(1 for s in skills if s["model_invoked"]),
              "mcp_servers": len(servers), "agents": len(agents),
              "skill_overrides": len(settings.get("skillOverrides") or {})}
    return {"skills": skills, "mcp_servers": servers, "agents": agents, "totals": totals}


def write_inventory(inventory, out):
    """Owner-only file; `scan_lib.write_summary` refuses any credential-shaped value."""
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", mode=0o700, exist_ok=True)
    scan_lib.write_summary(inventory, out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--projects", default="", help="comma list of repo paths whose .claude/skills and .mcp.json count")
    a = ap.parse_args()
    projects = [os.path.abspath(p) for p in a.projects.split(",") if p]
    inventory = build_inventory(os.path.expanduser("~"), projects)
    write_inventory(inventory, a.out)
    print(f"written {a.out}", file=sys.stderr)
    print(f"== inventory: {inventory['totals']}")
    by_source = {}
    for row in inventory["skills"]:
        by_source[row["source"]] = by_source.get(row["source"], 0) + 1
    print(f"   skills_by_source={dict(sorted(by_source.items(), key=lambda kv: -kv[1])[:12])}")
    print(f"   mcp_servers={[s['name'] for s in inventory['mcp_servers']]}")


if __name__ == "__main__":
    main()
