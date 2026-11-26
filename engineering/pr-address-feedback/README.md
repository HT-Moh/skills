# pr-address-feedback

Walk through the review comments on a pull request one by one. For each comment the skill shows
the reviewer's text verbatim, the diff context, the current code and evidence, then asks whether to
act on it or reply with reasoning. Nothing is edited or posted until you approve the resolution
plan. Pass a PR number or URL; with no argument it uses the PR for the current branch.

## What it produces

First an approved resolution plan: one entry per comment with the decision, the code change, the
exact reply text and whether the thread gets resolved. Then, once approved, the skill makes small
commits, pushes, posts the replies inside the existing threads with `gh api`, resolves the threads
the plan marks, and re-requests review from the human reviewers it addressed.

## Source

Adapted from [github/awesome-copilot](https://github.com/github/awesome-copilot) (MIT),
skill [pr-address-feedback](https://github.com/github/awesome-copilot/tree/main/skills/pr-address-feedback).
This copy replaces the upstream editor-specific tools with `gh` 2.88.0 commands.

## Install

Clone the repo once, link the skill into your personal skills directory, restart Claude Code:

```bash
git clone https://github.com/HT-Moh/skills.git ~/src/skills
ln -s ~/src/skills/engineering/pr-address-feedback ~/.claude/skills/pr-address-feedback
```

A symlink keeps `git pull` as the update path. `cp -r engineering/pr-address-feedback ~/.claude/skills/pr-address-feedback` gives a
frozen copy instead. Type `/pr-address-feedback` to run it; it does not fire on its own.
