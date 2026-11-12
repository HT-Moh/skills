"""Re-render a plan's Markdown and HTML after the engine changed its statuses.

The renderer belongs to the sibling skill claude-tune; this bridge finds it next to this
skill (both live in the same bucket) so the page never goes stale after an apply.
"""
import json
import os
import sys
from pathlib import Path

TUNE_SCRIPTS = os.path.realpath(os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "claude-tune", "scripts"))


def render_after_change(plan_path) -> Path:
    """Write <plan>.md and <plan>.html beside the plan; return the HTML path."""
    if TUNE_SCRIPTS not in sys.path:
        sys.path.insert(0, TUNE_SCRIPTS)
    import plan_render
    from plan_migrate import migrate_v1
    plan_path = Path(os.path.realpath(plan_path))  # through latest.json to the plan file itself
    with open(plan_path, encoding="utf-8") as fh:
        plan = migrate_v1(json.load(fh))
    md_path = plan_path.with_name(plan_path.name + ".md")
    html_path = plan_path.with_name(plan_path.name + ".html")
    plan_render.render_files(plan, str(plan_path), str(md_path), str(html_path))
    return html_path
