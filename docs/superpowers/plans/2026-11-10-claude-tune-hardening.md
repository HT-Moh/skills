# claude-tune hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close gaps G01–G34 so `/claude-tune` finishes its own run and `/claude-tune-apply` cannot break the user's setup, lose data or print a secret.

**Architecture:** `engineering/claude-tune-apply/scripts/` becomes a small package of single-purpose modules (schema, redaction, ops, backup, checks, consumers, store, report, CLI) owned by the apply skill and imported by the audit skill's renderer through a realpath-based `sys.path` entry. Plan schema 2 carries preconditions (`expect`, `sha256`), `consumers`, `checks` and `contains_secret`; the engine computes effective risk, orders by dependency, binds apply to the dry-run digest, writes atomically and redacts every printed string.

**Tech Stack:** Python 3.12 standard library, pytest 9, bash, one static HTML page. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-10-claude-tune-hardening-design.md`

## Global Constraints

- Standard library only; no PyYAML (parse frontmatter with a 20-line splitter in tests).
- Files under 300 lines, functions under 30 lines, at most four parameters, no boolean behaviour flag, no `sys.exit` outside `main()`: raise `PlanError` and let `main()` map it to exit 1.
- Every printed string in the apply engine goes through `redact.redact()`.
- Repo conventions: `name` frontmatter equals folder name, `metadata.author: Mohamed Habbat (https://github.com/HT-Moh)`, listed in `README.md`, `engineering/README.md`, `.claude-plugin/plugin.json`.
- The live plan `~/.claude/tune/plans/2026-11-10-59a7.json` keeps its statuses (P6-01 `applied`).
- Run tests from the repo root: `python3 -m pytest -q`.
- Commit after every task with the trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Review Focus

1. A plan item whose `depends_on` lists a `manual` item, selected together with it (`phase0`, `all`): the manual item must block the dependent. Test in Task 11.
2. `settings.json` edited by a running session between dry-run and apply: apply must refuse with the digest message, never write. Test in Task 12.
3. A `.env`-style or shell file diff (`API_KEY=...`, `export TOKEN=...`) and a JSON value containing `\"`: no secret substring in output. Test in Task 2.
4. Rollback after the user hand-edited the file: refuse without `--force`, restore mode and symlink otherwise. Test in Task 9.
5. A plan edited by hand to set `risk: safe` on a `statusLine` or `env` write: the engine must still ask. Test in Task 3.

---

### Task 1: Test scaffold and shared path setup

**Files:**
- Create: `pytest.ini`
- Create: `engineering/claude-tune-apply/tests/conftest.py`
- Create: `engineering/claude-tune/tests/conftest.py`
- Create: `engineering/claude-tune-apply/tests/test_imports.py`

**Interfaces:**
- Produces: fixture `scripts_dir` (Path to `engineering/claude-tune-apply/scripts`), fixture `tmp_home` (monkeypatched `HOME` pointing at `tmp_path / "home"` with `.claude/tune/plans` created), fixture `plan_file` (writes a minimal schema-2 plan dict given as parameter and returns its path).

- [ ] **Step 1: Write `pytest.ini`** with `[pytest]`, `testpaths = engineering`, `python_files = test_*.py`.
- [ ] **Step 2: Write both `conftest.py`** inserting `engineering/claude-tune-apply/scripts` and `engineering/claude-tune/scripts` (resolved from `__file__`) at the front of `sys.path`; define `tmp_home`, `scripts_dir`, `plan_file` in the apply conftest. Because the two scripts dirs both hold a `conftest`-visible `scan.py`/`apply.py` namespace, import modules by name only from the apply dir in apply tests.
- [ ] **Step 3: Write the failing test** `test_imports.py::test_modules_import` that imports `tune_ops`, `apply`, `plan_render` and asserts `tune_ops.OP_KINDS == plan_render.OP_KINDS`.
- [ ] **Step 4: Run** `python3 -m pytest -q engineering/claude-tune-apply/tests/test_imports.py`. Expected: PASS (current code already defines both tuples equal) or an import error to fix in the conftest.
- [ ] **Step 5: Commit** `test: scaffold pytest for claude-tune skills`.

### Task 2: `redact.py` (G11, G12)

**Files:**
- Create: `engineering/claude-tune-apply/scripts/redact.py`
- Test: `engineering/claude-tune-apply/tests/test_redact.py`
- Modify: `engineering/claude-tune-apply/scripts/tune_ops.py` (remove `REDACT_RE`, call `redact.redact` in `OpResult.diff`)

**Interfaces:**
- Produces: `redact(text: str) -> str`; `has_secret(text: str) -> bool`; `SECRET_VALUE_RES: tuple[re.Pattern, ...]`; `KEY_NAME_RE: re.Pattern` (case-sensitive `[A-Z0-9_]*(TOKEN|SECRET|KEY|PASSWORD|AUTHORIZATION)[A-Z0-9_]*`).

- [ ] **Step 1: Write failing tests**, one assertion each:
  - `test_json_pair_key_redacted`: `'"X_TOKEN": "abc"'` → contains `<redacted>`, not `abc`.
  - `test_json_pair_escaped_quote`: `'"X_TOKEN": "ab\\"cd"'` → `cd` absent.
  - `test_env_line`: `'API_KEY=abc123'` and `'export TOKEN=zz'` → values absent.
  - `test_lowercase_key_not_redacted`: `'"keyword-research": "off"'` → unchanged.
  - `test_value_prefixes`: each of `sk_live_abcdef0123`, `sk-ant-api03-xyz`, `github_pat_11AAA`, `ghp_` + 36 chars, `xoxb-1-2`, `AKIA` + 16 uppercase, `fc-abcdef`, `eyJ` + 30 chars + `.` → absent after `redact`.
  - `test_bearer_and_url_credentials`: `Authorization: Bearer abc.def` and `https://user:pw@host/` → `abc.def` and `pw` absent.
  - `test_private_key_block`: `-----BEGIN OPENSSH PRIVATE KEY-----\nAAAA\n-----END` → `AAAA` absent.
  - `test_high_entropy_token`: 40 random chars from `secrets.token_urlsafe(30)` → absent; the word `configuration-management-tooling` (low entropy) → present.
  - `test_has_secret`: `has_secret('"T": "sk_live_x"')` True, `has_secret("plain text")` False.
- [ ] **Step 2: Run** `python3 -m pytest -q engineering/claude-tune-apply/tests/test_redact.py`. Expected: FAIL `ModuleNotFoundError: redact`.
- [ ] **Step 3: Implement `redact.py`**: `KEY_NAME_RE`, `_JSON_PAIR_RE` (value as `"(?:[^"\\]|\\.)*"`), `_ENV_LINE_RE` (`(?m)^(\s*(?:export\s+)?KEY\s*=).*$`), `SECRET_VALUE_RES`, `_entropy(s) -> float`, `_redact_high_entropy(text)`, `redact(text)`, `has_secret(text)`. Keep under 120 lines.
- [ ] **Step 4: Replace `REDACT_RE` use in `tune_ops.OpResult.diff`** with `redact.redact` applied to `before` and `after` lines. Keep the existing `file_remove` behaviour for now (Task 6 changes it).
- [ ] **Step 5: Run** the redact tests and `test_imports`. Expected: PASS.
- [ ] **Step 6: Commit** `feat(apply): redact secrets by key and by value in every diff`.

### Task 3: `plan_schema.py`: validation, effective risk, ordering, migration (G02, G28, G12, part of G01)

**Files:**
- Create: `engineering/claude-tune-apply/scripts/plan_schema.py`
- Test: `engineering/claude-tune-apply/tests/test_plan_schema.py`
- Modify: `engineering/claude-tune/scripts/plan_render.py` (delete local `validate*`, `OP_KINDS`, `ID_RE`, `SECRET_RE`; import from `plan_schema`)
- Modify: `engineering/claude-tune-apply/scripts/tune_ops.py` (import `OP_KINDS` from `plan_schema`)
- Modify: `engineering/claude-tune/reference/plan.md` (schema 2 fields, `checks`, `json_upsert`, preconditions, effective risk rules)

**Interfaces:**
- Produces: `SCHEMA = 2`; `OP_KINDS` (adds `"json_upsert"`); `ID_RE = re.compile(r"P[0-6]-\d{2}")` used with `fullmatch`; `RISKS = ("safe","review","manual")`; `STATUSES`; `SENSITIVE_JSON_ROOTS = ("env","permissions","hooks","statusLine","mcpServers","apiKeyHelper")`; `class PlanError(Exception)`; `validate(plan: dict) -> list[str]` (empty list means valid); `effective_risk(item: dict) -> str`; `topo_order(items: list[dict]) -> list[dict]` (raises `PlanError` on cycle); `migrate_v1(plan: dict) -> dict` (in place, returns plan); `item_touches_secret_root(item) -> bool`.

- [ ] **Step 1: Write failing tests**:
  - `test_validate_accepts_minimal_v2` (one safe `json_set` item under `~/.claude/settings.json`, path `["autoCompactWindow"]`).
  - `test_validate_rejects_non_dict_item`, `test_validate_rejects_id_with_newline` (`"P1-02\n"`), `test_validate_rejects_string_depends_on`, `test_validate_detects_cycle` (A→B→A), `test_validate_rejects_string_values_for_append`, `test_validate_rejects_manual_op_in_review_item`, `test_validate_requires_unverified_when_docs_empty`, `test_validate_rejects_secret_value` (uses `redact.has_secret`), `test_validate_requires_consumers_for_env_delete`.
  - `test_effective_risk_floor_for_statusline` (`safe` declared, `json_set ["statusLine","command"]` → `"review"`), `test_effective_risk_floor_for_env`, `test_effective_risk_floor_for_file_remove`, `test_effective_risk_floor_for_claude_md`, `test_effective_risk_keeps_safe_for_enabledPlugins`, `test_effective_risk_manual_stays_manual`, `test_effective_risk_non_full_reversible_is_review`.
  - `test_topo_order_dependency_first_across_phases` (P2-01 depends on P5-01 → P5-01 first), `test_topo_order_cycle_raises`.
  - `test_migrate_v1_sets_schema_2_defaults_and_keeps_status` (item with `status: applied`, `verify: "x"` → `checks == [{"phase":"deferred","kind":"note","text":"x"}]`, `consumers == []`, `reversible == "full"`, status kept).
- [ ] **Step 2: Run** the file. Expected: FAIL `ModuleNotFoundError: plan_schema`.
- [ ] **Step 3: Implement `plan_schema.py`** (under 280 lines): type-check items and ops before field checks; `_validate_item`, `_validate_op`, `_validate_check`, `_validate_dependencies` (existence, string list, cycle via `topo_order`), `_validate_secrets` (`redact.has_secret(json.dumps(plan))`); `effective_risk`; `topo_order` (Kahn's algorithm, tiebreak `(phase, id)`); `migrate_v1`.
- [ ] **Step 4: Rewire `plan_render.py`** to `from plan_schema import validate, OP_KINDS, migrate_v1` via `sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "claude-tune-apply", "scripts"))`; call `migrate_v1` before `validate` when `plan["schema"] == 1`. Rewire `tune_ops` to import `OP_KINDS`.
- [ ] **Step 5: Update `reference/plan.md`** with the schema-2 example, the `checks` table, `json_upsert`, `expect`/`sha256`/`mode`, the effective-risk rules and the `consumers` requirement.
- [ ] **Step 6: Run** `python3 -m pytest -q`. Expected: PASS. Also run `python3 engineering/claude-tune/scripts/plan_render.py ~/.claude/tune/plans/2026-11-10-59a7.json --md /tmp/claude-1000/-media-bicatalyst-dell-laptop-src/59a7963b-a3fd-4185-bfe3-025363697695/scratchpad/p.md` and expect `valid:` (migration applied in memory only).
- [ ] **Step 7: Commit** `feat(apply): plan schema 2 with validation, effective risk, ordering, migration`.

### Task 4: Path safety and target typing in `tune_ops.py` (G18, G19, G26)

**Files:**
- Modify: `engineering/claude-tune-apply/scripts/tune_ops.py`
- Test: `engineering/claude-tune-apply/tests/test_paths.py`

**Interfaces:**
- Produces: `check_path(path: str) -> str` (returns the realpath or raises `PlanError`); `ALLOWED_ROOTS`, `REFUSED_PATTERNS`; `target_kind(path: str) -> str` in `{"missing","file","symlink","dangling-symlink","dir"}`; `read_text(path, overlay=None) -> str | None` raising nothing: OS and decode errors are returned through a new `ReadError(Exception)` caught by `preview` into `OpResult.errors`; files opened with `newline=""`.

- [ ] **Step 1: Write failing tests** using `tmp_home`:
  - `test_check_path_allows_claude_dir`, `test_check_path_allows_agents_dir`, `test_check_path_allows_git_worktree_file` (create `repo/.git/` and `repo/CLAUDE.md`), `test_check_path_refuses_claude_json`, `test_check_path_refuses_claude_json_via_symlink` (symlink `~/alias.json -> ~/.claude.json`), `test_check_path_refuses_symlink_into_etc` (symlink `~/.claude/x -> /etc`, path `~/.claude/x/passwd`), `test_check_path_refuses_zshrc_ssh_git_hooks_autostart`.
  - `test_target_kind_each_variant`.
  - `test_read_text_directory_returns_error_not_exception`, `test_read_text_binary_returns_error`, `test_read_text_preserves_crlf`.
- [ ] **Step 2: Run.** Expected: FAIL (new names missing; symlink cases pass today).
- [ ] **Step 3: Implement**: `check_path` with `os.path.realpath`, allowlist roots `~/.claude` (minus `~/.claude.json`), `~/.agents`, `~/.config/claude`, plus `_in_git_worktree(real)` (walk parents for `.git`, refuse when `.git` is itself in the path); `REFUSED_PATTERNS` for the rc, ssh, autostart, systemd paths and the system prefixes. `target_kind` with `os.lstat`. `read_text` catching `OSError`, `UnicodeDecodeError` into `ReadError`; `preview` turns `ReadError` into `OpResult.errors`.
- [ ] **Step 4: Run** all tests. Expected: PASS.
- [ ] **Step 5: Commit** `fix(apply): resolve real paths, allowlist targets, type targets before touching them`.

### Task 5: JSON ops: no phantom files, typed parents, `json_upsert`, `expect` (G03, G04, G22, G23)

**Files:**
- Modify: `engineering/claude-tune-apply/scripts/tune_ops.py` (move JSON previewers into new `ops_json.py` if `tune_ops.py` would exceed 300 lines)
- Test: `engineering/claude-tune-apply/tests/test_ops_json.py`

**Interfaces:**
- Produces: previewers `preview_json_set(op, before: str | None) -> OpResult`, `preview_json_delete`, `preview_json_append`, `preview_json_upsert`; shared `_json_parent(doc, keys) -> dict` raising `ValueError` when the parent is not a dict; `_check_expect(op, current_value) -> str | None` returning an error message when `"expect" in op` and the current value (or absence as `None`) differs.

- [ ] **Step 1: Write failing tests**:
  - `test_json_delete_missing_file_is_unchanged_and_writes_nothing`, `test_json_delete_empty_file_reports_error`, `test_json_set_string_parent_reports_error`, `test_json_set_top_level_list_reports_error`, `test_json_append_string_values_reports_error`, `test_json_append_adds_only_missing`, `test_json_upsert_replaces_matching_element` (hooks list, `match: {"matcher": "Bash"}`), `test_json_upsert_appends_when_no_match`, `test_expect_mismatch_reports_error` (`expect: 3650`, file has 90), `test_expect_null_means_absent`, `test_expect_match_proceeds`.
- [ ] **Step 2: Run.** Expected: FAIL on the new behaviours and names.
- [ ] **Step 3: Implement** in `ops_json.py` (import into `tune_ops.PREVIEWERS`); reuse the parsed document instead of re-parsing `before`; `changed` is false when `before is None` and the op is a delete.
- [ ] **Step 4: Run** all tests. Expected: PASS.
- [ ] **Step 5: Commit** `fix(apply): json ops keep files, type parents, upsert lists, honour expect`.

### Task 6: File ops idempotence, symlink op, hashes, modes (G24, G25, G27, G14 part)

**Files:**
- Modify: `engineering/claude-tune-apply/scripts/tune_ops.py` (file previewers; move to `ops_file.py` if over 300 lines)
- Test: `engineering/claude-tune-apply/tests/test_ops_file.py`

**Interfaces:**
- Produces: `preview_file_replace`, `preview_file_append`, `preview_file_create`, `preview_file_remove`, `preview_symlink`; `OpResult.mode: int | None`; `OpResult.summary_only: bool` (true for `file_remove`: diff prints `removes N lines, sha256 <hex[:16]>`); `_check_sha256(op, before) -> str | None`.

- [ ] **Step 1: Write failing tests**:
  - `test_file_replace_twice_when_new_contains_old` (`old="json"`, `new="json", "--no-session-persistence"` style) → second preview `changed is False`, no error.
  - `test_file_replace_deletion_twice` (`new=""`) → second preview unchanged, no error.
  - `test_file_append_line_match_not_substring` (`alias x=10` present, append `alias x=1` → changed).
  - `test_file_append_empty_content_is_error`.
  - `test_file_create_mode_applied_on_write` (`mode: 0o700` → `stat` after `write_result`).
  - `test_file_remove_diff_prints_summary_only` (content `TOKEN=abc` not in `diff()`).
  - `test_file_remove_symlink_records_link_target`, `test_file_remove_dangling_symlink_changes`, `test_file_op_on_symlink_target_is_error`, `test_file_op_on_directory_is_error`.
  - `test_symlink_missing_target_is_error`, `test_symlink_equivalent_target_unchanged` (relative vs absolute resolving to the same path).
  - `test_sha256_precondition_mismatch_is_error`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** the previewers; `write_result` applies `mode` for `file_create`; `preview_symlink` resolves the target relative to the link's directory and requires it to exist.
- [ ] **Step 4: Run** all tests. Expected: PASS.
- [ ] **Step 5: Commit** `fix(apply): idempotent file ops, symlink target checks, summary-only remove diffs`.

### Task 7: Atomic, verified writes (G17 part, G14)

**Files:**
- Modify: `engineering/claude-tune-apply/scripts/tune_ops.py` (`write_result`)
- Test: `engineering/claude-tune-apply/tests/test_write.py`

**Interfaces:**
- Produces: `write_result(r: OpResult) -> None` raising `StaleTargetError(PlanError)` when the current content differs from `r.before`; `atomic_write(path: str, data: str, mode: int) -> None` using a temp file in the same directory, `os.open(..., O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW)`, `os.replace`; `secure_umask()` called by `apply.main` (`os.umask(0o077)`).

- [ ] **Step 1: Write failing tests**: `test_write_refuses_when_target_changed_after_preview`, `test_write_preserves_existing_mode` (0o755 script stays 0o755), `test_write_new_file_is_0600_under_secure_umask`, `test_write_does_not_follow_symlink_target` (symlink target untouched, error raised), `test_write_leaves_no_temp_file_on_success`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** `atomic_write` and the re-read check in `write_result`.
- [ ] **Step 4: Run** all tests. Expected: PASS.
- [ ] **Step 5: Commit** `fix(apply): atomic writes that refuse stale targets and keep modes`.

### Task 8: `backup.py` (G09, G14, G19, G21)

**Files:**
- Create: `engineering/claude-tune-apply/scripts/backup.py` (move `make_backup` and manifest code out of `apply.py`)
- Test: `engineering/claude-tune-apply/tests/test_backup.py`

**Interfaces:**
- Produces: `BACKUP_ROOT`; `make_backup(item_id: str, results: list[OpResult]) -> Path` (dir named `%Y%m%d-%H%M%S.%f_<id>`, mode 0700, files 0600, `manifest.json` entries `{path, kind, existed, saved_as, parent_existed, mode, link_target, sha256_after}` deduped by path, `contains_secret: bool` computed with `redact.has_secret` over the saved copies); `record_after_hashes(bdir: Path) -> None` (fills `sha256_after` after writes); `purge_backup(bdir: Path) -> None`; `backup_dir_for(plan_item: dict) -> Path` validating `realpath` under `BACKUP_ROOT`.

- [ ] **Step 1: Write failing tests**: `test_backup_dir_unique_within_same_second` (two calls, two dirs), `test_manifest_records_mode_and_link_target`, `test_manifest_dedupes_same_path`, `test_contains_secret_flag_set_when_saved_copy_has_token`, `test_backup_dir_for_rejects_path_outside_root`, `test_backup_dir_for_rejects_saved_as_with_slash`, `test_tune_tree_created_0700`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** `backup.py` (under 150 lines); remove the moved code from `apply.py`.
- [ ] **Step 4: Run** all tests. Expected: PASS.
- [ ] **Step 5: Commit** `refactor(apply): backup module with modes, link targets, secret flag, unique dirs`.

### Task 9: Rollback hardening (G15, G16) and purge

**Files:**
- Modify: `engineering/claude-tune-apply/scripts/backup.py` (add `rollback_item`)
- Test: `engineering/claude-tune-apply/tests/test_rollback.py`

**Interfaces:**
- Produces: `rollback_item(plan: dict, item: dict, force: bool = False) -> list[str]` returning warning lines; raises `PlanError` when status is not `applied`, when the backup dir is outside `BACKUP_ROOT`, when any manifest path fails `check_path`, or when `sha256(current) != sha256_after` and not `force` (message names the file and `--force`); restores mode and symlinks; removes created files; removes created parents only when `parent_existed` is false; resets transitive dependents (via `depends_on`) to `proposed` and returns one warning per dependent; `dependents_of(plan, item_id) -> list[str]` transitive.

Note: `force` is a stated exception to the no-boolean-flag rule because it maps 1:1 to the CLI flag; keep it keyword-only.

- [ ] **Step 1: Write failing tests**: `test_rollback_refuses_unless_applied`, `test_rollback_refuses_backup_outside_root` (plan item `backup: "/tmp/x"`), `test_rollback_refuses_manifest_path_outside_allowlist`, `test_rollback_refuses_on_drift_without_force`, `test_rollback_with_force_restores_and_warns`, `test_rollback_restores_mode_0755`, `test_rollback_recreates_removed_symlink`, `test_rollback_resets_transitive_dependents`, `test_second_rollback_refused`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** `rollback_item`, `dependents_of`, `purge_backup` status handling (`applied-purged`).
- [ ] **Step 4: Run** all tests. Expected: PASS.
- [ ] **Step 5: Commit** `fix(apply): rollback validates paths, refuses drift, restores modes and links, resets dependents`.

### Task 10: `plan_store.py`: validated load, locked save, safe latest (G20, G21, G28)

**Files:**
- Create: `engineering/claude-tune-apply/scripts/plan_store.py`
- Test: `engineering/claude-tune-apply/tests/test_plan_store.py`
- Modify: `engineering/claude-tune/scripts/plan_render.py` (`--latest` uses `plan_store.point_latest`)

**Interfaces:**
- Produces: `PLANS_DIR`, `LOCK_PATH`; `load_plan(path: str | None) -> tuple[dict, Path]` (default `latest.json`; refuses a realpath outside `PLANS_DIR`; runs `migrate_v1` then `validate`, raising `PlanError` with the messages); `save_plan(plan: dict, path: Path) -> None` (temp file with unique name, 0600, `os.replace`); `locked() -> contextmanager` using `fcntl.flock` on `LOCK_PATH`; `point_latest(path: Path) -> None` (refuses outside `PLANS_DIR`; temp symlink + `os.replace`; raises `PlanError` listing applied item ids when the current latest plan has `applied` items and `path` differs, unless `force=True`).

- [ ] **Step 1: Write failing tests**: `test_load_refuses_plan_outside_plans_dir`, `test_load_migrates_v1_and_validates`, `test_load_reports_invalid_plan`, `test_save_is_atomic_and_0600`, `test_locked_blocks_second_holder` (use `fcntl.flock` with `LOCK_NB` from the test), `test_point_latest_refuses_when_old_plan_has_applied_items`, `test_point_latest_swaps_without_missing_window` (symlink exists at every step: assert `os.path.lexists` after).
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** and rewire `plan_render.py --latest`.
- [ ] **Step 4: Run** all tests. Expected: PASS.
- [ ] **Step 5: Commit** `feat(apply): plan store with validation, lock, atomic save and safe latest`.

### Task 11: Selection and dependency semantics (G01, G06, G07)

**Files:**
- Create: `engineering/claude-tune-apply/scripts/selection.py`
- Test: `engineering/claude-tune-apply/tests/test_selection.py`

**Interfaces:**
- Produces: `GROUP_EXCLUDED = ("applied","done","rolled_back","needs_user","failed","applied-purged")`; `select(plan, tokens: list[str]) -> list[dict]` (explicit ids select anything, groups exclude `GROUP_EXCLUDED`, empty result raises `PlanError("selection matched no item")`); `blockers(item, plan, succeeded: set[str], selected: set[str]) -> list[str]` (a dep is satisfied when status in `("applied","done")`, or `dep_id in succeeded`, or `dep_id in selected and risk != "manual"`, where the caller adds to `succeeded` only after a successful apply); `mark_done(plan, ids: list[str]) -> list[str]` (refuses non-manual ids, runs post checks via `checks.run_checks` from Task 14 once it exists; for this task call a `run_post_checks` hook that defaults to no-op; sets `status="done"`, `done_at`; returns the ids of items that became unblocked); `mark_undone(plan, ids) -> None`.

- [ ] **Step 1: Write failing tests**: `test_group_tokens_exclude_rolled_back`, `test_explicit_id_selects_rolled_back`, `test_empty_selection_raises`, `test_manual_dep_selected_is_still_blocker`, `test_manual_dep_done_satisfies`, `test_non_manual_dep_selected_but_not_yet_succeeded_blocks`, `test_non_manual_dep_succeeded_satisfies`, `test_mark_done_refuses_review_item`, `test_mark_done_sets_done_at_and_returns_unblocked`, `test_mark_undone_resets_to_proposed`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** `selection.py` (under 120 lines).
- [ ] **Step 4: Run** all tests. Expected: PASS.
- [ ] **Step 5: Commit** `fix(apply): manual dependencies need --done; groups skip rolled-back items`.

### Task 12: `runner.py`: chained dry-run, digest binding, per-item save and recovery (G05, G17, G31 engine side)

**Files:**
- Create: `engineering/claude-tune-apply/scripts/runner.py` (replaces `apply.run`)
- Test: `engineering/claude-tune-apply/tests/test_runner.py`

**Interfaces:**
- Produces: `@dataclass Preview(item_id, results: list[OpResult], blockers: list[str], errors: list[str])`; `dry_run(plan, items) -> tuple[list[Preview], str]` (one overlay dict shared across items in `topo_order`, returns previews and `digest = sha256(json.dumps([(id, kind, path, sha256(after or ""))...]))[:16]`); `apply_items(plan, items, plan_path, expect: str, confirmed: set[str]) -> list[str]` (recomputes the digest first and raises `PlanError("state changed since the dry run; run --dry-run again")` on mismatch; refuses any item with `effective_risk == "review"` not in `confirmed` with a message naming `--confirmed`; for each item in order: pre-checks (Task 14 hook, default no-op), backup, writes, post-checks, `record_after_hashes`, status `applied` with `applied_at`, `backup`, `files`; `save_plan` after every item; on exception restore from that item's backup and set `failed` with the message; an item with a `manual` op plus other ops ends as `needs_user`); `secret_backup_warning(item, bdir) -> str | None`.

- [ ] **Step 1: Write failing tests**: `test_dry_run_chains_overlay_between_items` (two items on one file: second diff is against the first's result), `test_digest_stable_for_same_state`, `test_apply_refuses_on_digest_mismatch_after_external_edit`, `test_apply_refuses_unconfirmed_review_item`, `test_apply_saves_plan_after_each_item` (make the second item's write fail by pointing at a directory; the first item is `applied` with `backup` on disk), `test_failed_item_is_restored_and_marked_failed`, `test_manual_plus_file_ops_ends_needs_user`, `test_secret_backup_warning_names_purge_command`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** `runner.py` (under 200 lines, functions under 30: `dry_run`, `_digest`, `apply_items`, `_apply_one`, `_recover`, `_finalize`).
- [ ] **Step 4: Run** all tests. Expected: PASS.
- [ ] **Step 5: Commit** `feat(apply): bind apply to the dry-run digest, save per item, recover failed items`.

### Task 13: `consumers.py` and `report.py` (G08, G30)

**Files:**
- Create: `engineering/claude-tune-apply/scripts/consumers.py`
- Create: `engineering/claude-tune-apply/scripts/report.py` (replaces `show_item`, `print_list`)
- Test: `engineering/claude-tune-apply/tests/test_consumers.py`, `engineering/claude-tune-apply/tests/test_report.py`

**Interfaces:**
- Produces: `find_consumers(names: list[str], roots: list[str] | None = None) -> list[str]` (greps for each name in `~/.agents/skills`, `~/.claude/skills`, `~/.claude/hooks`, `~/.claude/CLAUDE.md`, `~/.claude/rules`, `~/.claude.json` (key names only), and `crontab -l` output; returns `"<path or 'crontab'>: <name>"` lines; never returns file content); `key_names_touched(item) -> list[str]` (last JSON key for `env`/`permissions`/`hooks` ops); `explain(item, plan) -> str` (why, evidence, impact, effective risk with floor reason, consumers (declared plus discovered), depends_on with each status, checks, reversible, takes_effect, docs); `show_preview(preview: Preview, item) -> str` (header line `== ID title [effective risk]`, `WARNING EXEC` when a hook, statusLine or `~/.claude/hooks` path is written, `WARNING PERMISSION` when `permissions` is written with the removed list entries named, consumers line, blockers line, diffs via `OpResult.diff`); `list_table(plan) -> str` (columns id, ph, risk, status, blocked-by, title; footer `Next:` naming the first unblocked item and, for a manual one, its `--done` command). All through `redact.redact`.

- [ ] **Step 1: Write failing tests**: `test_find_consumers_names_skill_file_not_content` (fixture skill with `curl ...$BROWSERLESS_TOKEN` → result line contains the path and `BROWSERLESS_TOKEN`, not `curl`), `test_key_names_touched_env_delete`, `test_explain_lists_dependency_statuses`, `test_show_preview_warns_exec_for_hooks`, `test_show_preview_warns_permission_and_names_removed_entries`, `test_list_table_has_blocked_by_and_next`, `test_all_output_is_redacted` (manual text with `sk_live_x`).
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** both modules (each under 200 lines).
- [ ] **Step 4: Run** all tests. Expected: PASS.
- [ ] **Step 5: Commit** `feat(apply): explain items, discover consumers, warn on exec and permission writes`.

### Task 14: `checks.py` (G32)

**Files:**
- Create: `engineering/claude-tune-apply/scripts/checks.py`
- Test: `engineering/claude-tune-apply/tests/test_checks.py`
- Modify: `runner.py`, `selection.py` (wire pre/post checks)

**Interfaces:**
- Produces: `CHECK_KINDS`; `CMD_ALLOWLIST = ("claude","test","stat","grep","ls","readlink")`; `run_checks(item, phase: str) -> list[CheckResult]` with `@dataclass CheckResult(kind, ok: bool, detail: str)`; kinds `json_equals(file, path, value)`, `json_absent(file, path)`, `file_contains(file, text)`, `file_absent(file)`, `file_sha256(file, sha256)`, `file_mode(file, mode)`, `cmd_exit(argv, timeout_s=10)` (argv[0] must be in the allowlist; `subprocess.run` with timeout, no shell), `note(text)` always ok. In `runner._apply_one`: failing `pre` → `PlanError` before backup; failing `post` → rollback that item, status `failed`. In `selection.mark_done`: failing `post` → `PlanError`.

- [ ] **Step 1: Write failing tests**: one per kind for ok and not-ok, `test_cmd_exit_refuses_non_allowlisted`, `test_cmd_exit_times_out`, `test_pre_check_failure_refuses_before_backup` (no backup dir created), `test_post_check_failure_rolls_back_item`, `test_mark_done_runs_post_checks`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** and wire.
- [ ] **Step 4: Run** all tests. Expected: PASS.
- [ ] **Step 5: Commit** `feat(apply): structured pre, post and deferred checks`.

### Task 15: `apply.py` CLI rewrite (G07, G34)

**Files:**
- Modify: `engineering/claude-tune-apply/scripts/apply.py` (rewrite; under 150 lines)
- Test: `engineering/claude-tune-apply/tests/test_cli.py`

**Interfaces:**
- Produces: argparse with `selection` (nargs `*`), `--plan`, `--list`, `--dry-run`, `--expect DIGEST`, `--confirmed IDS` (comma-separated), `--rollback ID [ID...]`, `--force`, `--done ID [ID...]`, `--undone ID [ID...]`, `--explain ID`, `--purge-backup ID`, `--render`; `main(argv) -> int`; every branch inside `plan_store.locked()`; after any mutation call `render.render_after_change(plan_path)` (Task 16) when `--render` or always for mutations; exit codes: 0 ok, 1 `PlanError`, 2 usage; a missing plan with `--list` prints the hint and returns 0, any other action returns 1.

- [ ] **Step 1: Write failing tests** via `subprocess.run([sys.executable, apply_py, ...], env=tmp_home_env)`: `test_list_without_plan_exits_0`, `test_rollback_without_plan_exits_1`, `test_dry_run_prints_digest`, `test_apply_without_expect_exits_1_with_hint`, `test_done_multiple_ids`, `test_done_review_item_exits_1`, `test_explain_prints_consumers_and_deps`, `test_apply_safe_item_end_to_end` (dry-run, capture digest, apply with `--expect`, file changed, status applied), `test_no_sys_exit_outside_main` (grep the source for `sys.exit` occurrences: exactly one, in `main`'s caller `if __name__`).
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Rewrite `apply.py`** as thin dispatch over `plan_store`, `selection`, `runner`, `backup`, `report`.
- [ ] **Step 4: Run** all tests. Expected: PASS. Check `wc -l` of every script under 300.
- [ ] **Step 5: Commit** `refactor(apply): thin CLI over store, selection, runner, backup, report`.

### Task 16: Page and renderer (G29, G20 render hook)

**Files:**
- Modify: `engineering/claude-tune/templates/plan.html`
- Modify: `engineering/claude-tune/scripts/plan_render.py`
- Create: `engineering/claude-tune-apply/scripts/render.py` (`render_after_change(plan_path) -> Path` importing `plan_render` from the sibling skill and writing `<plan>.md` and `<plan>.html`)
- Test: `engineering/claude-tune/tests/test_plan_render.py`

**Interfaces:**
- Produces: `render_html(plan, rendered_at: str, plan_mtime: str) -> str` embedding `plan` JSON with `<` as `<` and `rendered_at`/`plan_mtime` in a `data-` attribute; template JS: `blockers(item)` from `depends_on` and statuses, chip text `needs P0-01 (manual, not done)`; ticking a blocked item appends a footer warning naming the blockers; "Select phase" skips `manual`; footer renders three lines: `/claude-tune-apply --dry-run <ids>`, `/claude-tune-apply <ids> --expect <digest from dry-run>`, `/claude-tune-apply --done <manual ids>`, each with its own copy button; Rollback row hidden when `risk == "manual"`; legend line under the header; stale line `rendered <rendered_at> from plan saved <plan_mtime>; re-render with /claude-tune-apply --render`; no `innerHTML` with plan data (search the template: zero occurrences of `innerHTML` with a plan field).

- [ ] **Step 1: Write failing tests**: `test_html_escapes_lt_in_json` (`"<img"` in a title → `<img` in output, no raw `<img`), `test_html_has_no_innerHTML_with_plan_fields` (regex over the template), `test_html_embeds_rendered_at_and_mtime`, `test_md_lists_consumers_and_blockers`, `test_render_after_change_writes_md_and_html`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** template and renderer changes within the existing token CSS; keep the template under 300 lines (split CSS into `templates/plan.css` inlined by the renderer if needed).
- [ ] **Step 4: Run** tests; open the rendered page for the live plan in a text check: `grep -c 'needs P0-01' <plan>.html` is at least 1.
- [ ] **Step 5: Commit** `feat(tune): page shows blockers, legend, staleness and three commands; no innerHTML`.

### Task 17: `scan.py` hygiene and split (G13, G34)

**Files:**
- Modify: `engineering/claude-tune/scripts/scan.py` (split into `scan.py` CLI and `scan_lib.py`)
- Test: `engineering/claude-tune/tests/test_scan.py`

**Interfaces:**
- Produces: `prefix(cmd: str) -> str` returning `argv[0]` basename plus the subcommand only when `argv[0]` is in `KNOWN_TOOLS = ("git","gh","kubectl","docker","npm","uv","python3","pytest","curl","ssh","rtk")`, otherwise `argv[0]` basename only; `hook_key(command: str) -> str` basename of argv[0]; prompts emitted as `sha256(text)[:12]` plus length; `write_summary(out: dict, path: str)` with `os.open(..., 0o600)` after `redact.has_secret(json.dumps(out))` is False (else raise); `scan_file` split into `classify_line`, `record_user`, `record_assistant`, each under 30 lines; events filtered by `when >= cutoff`; non-dict events skipped.

- [ ] **Step 1: Write failing tests**: `test_prefix_drops_export_values` (`export TOKEN=abc` → `export`), `test_prefix_known_tool_keeps_subcommand` (`git -C x status` → `git status`), `test_hook_key_is_basename` (`curl https://x/?token=abc` → `curl`), `test_prompts_are_hashed`, `test_write_summary_0600_and_refuses_secret`, `test_events_before_cutoff_skipped`, `test_non_dict_event_skipped`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** the split; keep output keys identical except `repeated_prompts_sessions` entries become `(n, hash, length)`.
- [ ] **Step 4: Run** all tests and `python3 engineering/claude-tune/scripts/scan.py --days 1 --out /tmp/claude-1000/-media-bicatalyst-dell-laptop-src/59a7963b-a3fd-4185-bfe3-025363697695/scratchpad/scan1.json` (expect `written`, mode 600).
- [ ] **Step 5: Commit** `fix(tune): scan never emits command tails or prompt text; split scan_file`.

### Task 18: Skill texts and shell scripts (G10, G31, G33)

**Files:**
- Modify: `engineering/claude-tune/SKILL.md`
- Modify: `engineering/claude-tune-apply/SKILL.md`
- Modify: `engineering/claude-tune/scripts/inventory.sh`
- Modify: `engineering/claude-tune/reference/report.md` (five levers plus link in the terminal; rest on the page)
- Test: `engineering/claude-tune/tests/test_skill_files.py`

**Interfaces:**
- claude-tune frontmatter: remove `context`, `agent`, `background`, `when_to_use`; keep `disable-model-invocation: true`, `arguments`, `argument-hint`, `effort: high`, `allowed-tools` with `${CLAUDE_SKILL_DIR}` and `/home/bicatalyst/...` absolute paths (no `~`); add `metadata: {author: "Mohamed Habbat (https://github.com/HT-Moh)"}`. Body: step 3 launches all agents in one message and waits for every report before step 4; procedure note names `&&`, `||`, `;`, `|`, `&`, newline as the splitters; rule 7 "never end the turn while an agent you launched is running". Injected blocks unchanged (`bash ${CLAUDE_SKILL_DIR}/scripts/inventory.sh $days`).
- claude-tune-apply frontmatter: `allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/apply.py *) Read(/home/bicatalyst/.claude/tune/plans/**) AskUserQuestion`; remove `when_to_use`; add `metadata.author`. Procedure: `--dry-run` first; if any `review` item or `WARNING` line, one multi-select `AskUserQuestion` listing each review item with its consumers and warnings, unchecked by default when blockers or consumers exist; then `apply.py <ids> --expect <digest> --confirmed <ticked ids>`; summary prints per item the `takes_effect` value, consumers, backup dir, purge warning when present, rollback command, `--done` commands for manual items.
- `inventory.sh`: `case "$DAYS" in ''|*[!0-9]*) echo "days must be an integer"; exit 0;; esac` before use.

- [ ] **Step 1: Write failing tests**: `test_frontmatter_parses_and_has_required_keys` (20-line splitter: text between the first two `---` lines, `key: value` pairs; assert `name` equals folder, `metadata.author` present, no `when_to_use`, no `context`), `test_injected_blocks_have_no_splitters` (regex over ```! blocks for `&&|\|\||;|\|`), `test_allowed_tools_have_no_tilde`, `test_apply_read_rule_is_plans_only`, `test_inventory_rejects_non_integer_days` (`bash inventory.sh abc` exit 0, output contains `integer`).
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Edit the four files.**
- [ ] **Step 4: Run** tests and `claude plugin validate /media/bicatalyst/dell_laptop/src/skills` (expect `Validation passed`).
- [ ] **Step 5: Commit** `fix(tune): run in the invoking session, wait for agents, narrow apply reads, confirm per item`.

### Task 19: Migrate the live plan, install, register, review

**Files:**
- Modify: `~/.claude/tune/plans/2026-11-10-59a7.json` (via `apply.py --migrate` plus the three amendments)
- Modify: `README.md`, `engineering/README.md`, `.claude-plugin/plugin.json`
- Replace: `~/.agents/skills/claude-tune`, `~/.agents/skills/claude-tune-apply` with symlinks into the repo

- [ ] **Step 1: Add `--migrate`** to `apply.py` (loads with migration, saves schema 2, prints the items whose effective risk rose) with a CLI test `test_migrate_rewrites_schema_and_reports_risk_changes`.
- [ ] **Step 2: Run** `python3 engineering/claude-tune-apply/scripts/apply.py --migrate --plan ~/.claude/tune/plans/2026-11-10-59a7.json`. Expected: `schema 2`, P6-01 still `applied`, P1-05 listed as risk raised to `review`.
- [ ] **Step 3: Amend the plan** with a one-off `python3 -I` snippet: P0-08 deny list append `Read(~/.claude/tune/backups/**)`; P0-03 `depends_on` add `P0-06` and `consumers` = the three skill paths found by `consumers.find_consumers(["BROWSERLESS_TOKEN"])`. Then `apply.py --render --plan <plan>`. Expected: `valid:`.
- [ ] **Step 4: Replace the installed copies**: `rm -r ~/.agents/skills/claude-tune ~/.agents/skills/claude-tune-apply && ln -s /media/bicatalyst/dell_laptop/src/skills/engineering/claude-tune ~/.agents/skills/claude-tune && ln -s .../claude-tune-apply ~/.agents/skills/claude-tune-apply`; run `claude plugin validate ~/.agents/skills` and `python3 ~/.claude/skills/claude-tune-apply/scripts/apply.py --list` (expect the table with `blocked-by` and `Next:`).
- [ ] **Step 5: Register** both skills in `README.md`, `engineering/README.md`, `.claude-plugin/plugin.json` per repo `CLAUDE.md`.
- [ ] **Step 6: Run** `python3 -m pytest -q` (all green), `wc -l engineering/*/scripts/*.py engineering/*/templates/*` (all under 300).
- [ ] **Step 7: Commit** `chore: register claude-tune skills, migrate live plan to schema 2`, then request a whole-branch review with `superpowers:requesting-code-review` before opening the PR.
