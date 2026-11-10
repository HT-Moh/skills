#!/usr/bin/env bash
# Fast inventory of Claude Code session data for the last N days. Read-only.
# Usage: inventory.sh [days]   (default 30). Prints a TSV table and config facts.
set -u
DAYS="${1:-30}"
case "$DAYS" in ''|*[!0-9]*) echo "days must be an integer, got '$DAYS'"; exit 0;; esac
ROOT="$HOME/.claude/projects"
[ -d "$ROOT" ] || { echo "no $ROOT"; exit 0; }

echo "window_days=$DAYS  claude_version=$(claude --version 2>/dev/null | head -1)"
echo "projects_dir_size=$(du -sh "$ROOT" 2>/dev/null | cut -f1)"
INSIGHTS="$HOME/.claude/usage-data/report.html"
if [ -f "$INSIGHTS" ]; then
  # Built-in /insights report: a second opinion on friction; headings only, never the body
  echo "insights_report=$INSIGHTS  modified=$(date -r "$INSIGHTS" +%F)"
  grep -o '<h[23][^>]*>[^<]\{1,80\}' "$INSIGHTS" 2>/dev/null | sed 's/<[^>]*>/  /' | head -20
else
  echo "insights_report=none (run /insights in Claude Code to produce one)"
fi
echo
echo "sessions	interactive	headless	size_mb	last_active	project_dir"
find "$ROOT" -mindepth 2 -maxdepth 2 -name '*.jsonl' -mtime "-$DAYS" -printf '%h\t%s\t%TY-%Tm-%Td\t%p\n' 2>/dev/null \
| awk -F'\t' '
  {
    n[$1]++; s[$1]+=$2; if ($3>last[$1]) last[$1]=$3; files[$1]=files[$1] " " $4
  }
  END { for (k in n) printf "%d\t%d\t%s\t%s\t%s\n", n[k], s[k]/1048576, last[k], k, files[k] }' \
| sort -nr | head -15 \
| while IFS=$'\t' read -r n mb last dir files; do
    inter=0; head_=0
    for f in $files; do
      # entrypoint sits in the first user event, usually 4-7 KB into the file
      e=$(head -c 400000 "$f" 2>/dev/null | grep -o '"entrypoint":"[^"]*"' | head -1 | cut -d'"' -f4)
      case "$e" in cli) inter=$((inter+1));; sdk*) head_=$((head_+1));; esac
    done
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$n" "$inter" "$head_" "$mb" "$last" "${dir#$ROOT/}"
  done

echo
echo "subagent_files_in_window=$(find "$ROOT" -mindepth 3 -path '*/subagents/agent-*.jsonl' -mtime "-$DAYS" 2>/dev/null | wc -l)"
echo "largest_sessions:"
find "$ROOT" -mindepth 2 -maxdepth 2 -name '*.jsonl' -mtime "-$DAYS" -printf '%s\t%p\n' 2>/dev/null | sort -nr | head -3 \
| awk -F'\t' '{printf "  %d MB  %s\n", $1/1048576, $2}'

exit 0
