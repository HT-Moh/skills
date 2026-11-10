#!/usr/bin/env bash
# Fetch the Claude Code docs as markdown into a scratch dir. Read-only network GETs.
# Usage: docs_fetch.sh <outdir>
set -u
OUT="${1:?outdir}"; mkdir -p "$OUT"
BASE="https://code.claude.com/docs/en"
PAGES="best-practices costs context-window memory claude-directory settings-reference settings permissions permission-modes env-vars hooks hooks-guide skills sub-agents commands interactive-mode headless worktrees model-config statusline scheduled-tasks checkpointing mcp cli-reference"
ok=0; fail=""
for p in $PAGES; do
  if curl -fsSL -m 30 "$BASE/$p.md" -o "$OUT/$p.md" 2>/dev/null && [ -s "$OUT/$p.md" ]; then ok=$((ok+1)); else fail="$fail $p"; fi
done
echo "fetched=$ok of $(echo $PAGES | wc -w) into $OUT${fail:+  failed:$fail}"
echo "sizes:"; wc -c "$OUT"/*.md 2>/dev/null | sort -nr | head -5 | awk '{printf "  %s %s\n",$1,$2}'
echo "grep a setting with: grep -n -i '<name>' $OUT/*.md"
