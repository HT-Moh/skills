#!/usr/bin/env bash
# Config facts for the tuning audit. Read-only. Prints key names, never secret values.
set -u
C="$HOME/.claude"; S="$C/settings.json"; J="$HOME/.claude.json"
jqr() { jq -r "$1" "$2" 2>/dev/null; }

echo "== settings.json"
[ -f "$S" ] || { echo "missing"; exit 0; }
echo "defaultMode=$(jqr '.permissions.defaultMode // "unset"' "$S")  model=$(jqr '.model // "unset"' "$S")  effortLevel=$(jqr '.effortLevel // "unset"' "$S")"
echo "autoCompactWindow=$(jqr '.autoCompactWindow // "unset"' "$S")  cleanupPeriodDays=$(jqr '.cleanupPeriodDays // "unset(30)"' "$S")  sandbox=$(jqr '.sandbox.enabled // "unset"' "$S")"
echo "allow_rules=$(jqr '.permissions.allow // [] | length' "$S")  deny_rules=$(jqr '.permissions.deny // [] | length' "$S")  ask_rules=$(jqr '.permissions.ask // [] | length' "$S")"
echo "hooks_events=$(jqr '.hooks // {} | keys | join(",")' "$S")"
echo "env_keys=$(jqr '.env // {} | keys | join(",")' "$S")"
echo "env_keys_that_look_secret=$(jqr '.env // {} | to_entries | map(select(.key|test("TOKEN|KEY|SECRET|PASS";"i")) | select(.value|test("^\\$\\{")|not) | .key) | join(",")' "$S")"
echo "plugins_enabled=$(jqr '.enabledPlugins // {} | to_entries | map(select(.value==true)) | length' "$S")  plugins_disabled=$(jqr '.enabledPlugins // {} | to_entries | map(select(.value==false)) | length' "$S")"
echo "skillOverrides=$(jqr '.skillOverrides // {} | length' "$S")"
SL=$(jqr '.statusLine.command // ""' "$S"); SLP=$(echo "$SL" | grep -oE '(/[^ "]+)' | head -1)
if [ -n "$SL" ]; then echo "statusLine=set  script=$SLP  script_exists=$([ -n "$SLP" ] && [ -e "$SLP" ] && echo yes || echo no)"; else echo "statusLine=unset"; fi

echo "== ~/.claude.json"
if [ -f "$J" ]; then
  echo "user_mcp_servers=$(jqr '.mcpServers // {} | keys | join(",")' "$J")"
  echo "project_entries=$(jqr '.projects // {} | keys | length' "$J")  project_entries_with_missing_path=$(jqr '.projects // {} | keys[]' "$J" | while read -r p; do [ -d "$p" ] || echo x; done | wc -l)"
  # Key names only, never values. A value starting with ${ is an env reference, not a literal.
  echo "literal_secret_fields=$(jq -r '[paths(scalars) as $p | ($p|map(tostring)) as $s | select(($s|join(".")) | test("\\.(env|headers)\\.")) | select(($s|last) | test("TOKEN|_KEY$|API_KEY|SECRET|PASSWORD|^Authorization$";"i")) | select(getpath($p)|tostring|test("^\\$\\{")|not) | ($s|join("."))] | join(" ; ")' "$J" 2>/dev/null | head -c 600)"
fi

echo "== files"
echo "skills_total=$(ls -1 "$C/skills" 2>/dev/null | wc -l)  skills_symlinks=$(find "$C/skills" -maxdepth 1 -type l 2>/dev/null | wc -l)  agents=$(ls -1 "$C/agents" 2>/dev/null | wc -l)  commands=$(ls -1 "$C/commands" 2>/dev/null | wc -l)"
echo "skill_description_chars=$(find -L "$C/skills" -maxdepth 2 -name SKILL.md 2>/dev/null | xargs -r grep -h -m1 '^description:' | wc -c)"
echo "plugin_hook_files=$(find "$C/plugins/cache" -name hooks.json 2>/dev/null | wc -l)  plugin_temp_dirs=$(find "$C/plugins/cache" -maxdepth 1 -name 'temp_*' 2>/dev/null | wc -l)"
echo "claude_md_global_tokens~=$(( $(cat "$C/CLAUDE.md" "$C"/rules/*.md 2>/dev/null | wc -c) / 4 ))"
echo "backups_with_settings=$(ls "$C"/settings.json.* "$C"/backups/ 2>/dev/null | wc -l)"
echo "projects_dir_gb=$(du -s "$C/projects" 2>/dev/null | awk '{printf "%.1f", $1/1048576}')"

echo "== project instruction files (under \$PWD, depth 3)"
find . -maxdepth 3 \( -name CLAUDE.md -o -name AGENTS.md -o -name RULES.md \) -not -path '*/node_modules/*' -not -path '*/.worktrees/*' 2>/dev/null \
| while read -r f; do
    if [ -L "$f" ] && [ ! -e "$f" ]; then echo "BROKEN_SYMLINK $f"; continue; fi
    sz=$(wc -c < "$f" 2>/dev/null || echo 0); [ "$sz" -eq 0 ] && echo "EMPTY $f" && continue
    printf '%6d tokens~  %s\n' $((sz/4)) "$f"
  done | sort -nr | head -25

exit 0
