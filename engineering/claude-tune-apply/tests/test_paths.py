import os

import pytest

import tune_ops
from plan_schema import PlanError


def test_check_path_allows_claude_dir(tmp_home):
    p = tmp_home / ".claude" / "settings.json"
    assert tune_ops.check_path(str(p)) == str(p.resolve())


def test_check_path_allows_agents_dir(tmp_home):
    p = tmp_home / ".agents" / "skills" / "x" / "SKILL.md"
    assert tune_ops.check_path(str(p)).endswith("SKILL.md")


def test_check_path_allows_git_worktree_file(tmp_home):
    repo = tmp_home / "src" / "repo"
    (repo / ".git").mkdir(parents=True)
    assert tune_ops.check_path(str(repo / "CLAUDE.md")).endswith("CLAUDE.md")


def test_check_path_refuses_file_outside_allowlist(tmp_home):
    with pytest.raises(PlanError):
        tune_ops.check_path(str(tmp_home / "random.txt"))


def test_check_path_refuses_claude_json(tmp_home):
    with pytest.raises(PlanError, match="claude.json"):
        tune_ops.check_path(str(tmp_home / ".claude.json"))


def test_check_path_refuses_claude_json_via_symlink(tmp_home):
    (tmp_home / ".claude.json").write_text("{}")
    link = tmp_home / ".claude" / "alias.json"
    os.symlink(tmp_home / ".claude.json", link)
    with pytest.raises(PlanError, match="claude.json"):
        tune_ops.check_path(str(link))


def test_check_path_refuses_symlink_into_etc(tmp_home):
    link = tmp_home / ".claude" / "x"
    os.symlink("/etc", link)
    with pytest.raises(PlanError):
        tune_ops.check_path(str(link / "passwd"))


@pytest.mark.parametrize("rel", [".zshrc", ".bashrc", ".profile", ".ssh/authorized_keys",
                                 ".config/autostart/x.desktop", ".config/systemd/user/x.service",
                                 "src/repo/.git/hooks/pre-commit"])
def test_check_path_refuses_sensitive_user_paths(tmp_home, rel):
    (tmp_home / "src" / "repo" / ".git").mkdir(parents=True)
    with pytest.raises(PlanError):
        tune_ops.check_path(str(tmp_home / rel))


def test_target_kind_each_variant(tmp_home):
    d = tmp_home / ".claude"
    (d / "f").write_text("x")
    os.symlink(d / "f", d / "l")
    os.symlink(d / "nope", d / "dangling")
    assert tune_ops.target_kind(str(d / "missing")) == "missing"
    assert tune_ops.target_kind(str(d / "f")) == "file"
    assert tune_ops.target_kind(str(d / "l")) == "symlink"
    assert tune_ops.target_kind(str(d / "dangling")) == "dangling-symlink"
    assert tune_ops.target_kind(str(d)) == "dir"


def test_read_text_directory_returns_error_not_exception(tmp_home):
    with pytest.raises(tune_ops.ReadError):
        tune_ops.read_text(str(tmp_home / ".claude"))


def test_read_text_binary_returns_error(tmp_home):
    p = tmp_home / ".claude" / "bin"
    p.write_bytes(b"\xff\xfe\x00binary")
    with pytest.raises(tune_ops.ReadError):
        tune_ops.read_text(str(p))


def test_read_text_preserves_crlf(tmp_home):
    p = tmp_home / ".claude" / "crlf.txt"
    p.write_bytes(b"a\r\nb\r\n")
    assert tune_ops.read_text(str(p)) == "a\r\nb\r\n"


def test_preview_turns_read_error_into_op_error(tmp_home):
    op = {"kind": "file_append", "file": str(tmp_home / ".claude"), "content": "x"}
    r = tune_ops.preview(op)
    assert r.errors and not r.changed


def test_check_path_refuses_home_itself_as_worktree(tmp_home):
    (tmp_home / ".git").mkdir()
    with pytest.raises(PlanError):
        tune_ops.check_path(str(tmp_home / "notes.txt"))


def test_check_path_refuses_dot_dir_repo_under_home(tmp_home):
    (tmp_home / ".cache" / "repo" / ".git").mkdir(parents=True)
    with pytest.raises(PlanError):
        tune_ops.check_path(str(tmp_home / ".cache" / "repo" / "x.md"))


def test_check_path_refuses_git_dir_any_case(tmp_home):
    (tmp_home / "src" / "repo" / ".git").mkdir(parents=True)
    with pytest.raises(PlanError):
        tune_ops.check_path(str(tmp_home / "src" / "repo" / ".GIT" / "config"))


def test_check_path_refuses_system_repo(tmp_home, monkeypatch):
    monkeypatch.setattr(tune_ops, "_in_git_worktree", lambda real: True, raising=False)
    import ops_base
    monkeypatch.setattr(ops_base, "_in_git_worktree", lambda real: True)
    with pytest.raises(PlanError):
        tune_ops.check_path("/usr/share/repo/CLAUDE.md")


def test_check_path_refuses_lexical_ssh_even_when_symlinked_elsewhere(tmp_home):
    (tmp_home / ".claude" / "sshdir").mkdir()
    os.symlink(tmp_home / ".claude" / "sshdir", tmp_home / ".ssh")
    with pytest.raises(PlanError):
        tune_ops.check_path(str(tmp_home / ".ssh" / "config"))


def test_check_path_refuses_rc_basename_inside_repo(tmp_home):
    (tmp_home / "src" / "dotfiles" / ".git").mkdir(parents=True)
    with pytest.raises(PlanError):
        tune_ops.check_path(str(tmp_home / "src" / "dotfiles" / ".zshrc"))


def test_check_path_refuses_repo_file_that_home_startup_file_links_to(tmp_home):
    repo = tmp_home / "src" / "dotfiles"
    (repo / ".git").mkdir(parents=True)
    (repo / "zshrc").write_text("x")
    os.symlink(repo / "zshrc", tmp_home / ".zshrc")
    with pytest.raises(PlanError):
        tune_ops.check_path(str(repo / "zshrc"))


@pytest.mark.parametrize("name", [".zshenv", ".zlogin", ".zlogout", ".bash_login", ".bash_logout", ".bash_aliases"])
def test_check_path_refuses_more_startup_files(tmp_home, name):
    with pytest.raises(PlanError):
        tune_ops.check_path(str(tmp_home / name))
