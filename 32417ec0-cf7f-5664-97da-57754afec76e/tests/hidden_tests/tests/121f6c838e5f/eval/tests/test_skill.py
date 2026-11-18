"""declscope skill install / uninstall / list: destinations, agents, scopes, states and refusals."""

import re

from conftest import assert_golden, assert_run_golden, normalize

STAMP = re.compile(r'^x-embedded-at: "\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ"$', re.M)


def installed(path) -> str:
    """An installed SKILL.md with its install timestamp (the one volatile line) replaced."""
    text = path.read_text()
    assert len(STAMP.findall(text)) == 1, text[:600]
    return STAMP.sub('x-embedded-at: "<timestamp>"', text)


def home_env(workdir):
    home = workdir / "home"
    home.mkdir(exist_ok=True)
    return {"HOME": str(home)}


def test_install_into_dir(run, workdir):
    """CATCHES: an install that does not write both embedded skills under -dir, prints a different result
    table, or writes manifests without the x-embedded-by/version/digest stamp the reference adds."""
    r = run(["skill", "install", "-dir", "dest"])
    assert_run_golden(__file__, "install_dir", r, workdir)
    assert sorted(str(p.relative_to(workdir)) for p in (workdir / "dest").rglob("*") if p.is_file()) == [
        "dest/declscope-adoption/SKILL.md", "dest/declscope-authoring/SKILL.md"]
    assert_golden(__file__, "authoring_skill_md", installed(workdir / "dest/declscope-authoring/SKILL.md"))
    assert_golden(__file__, "adoption_skill_md", installed(workdir / "dest/declscope-adoption/SKILL.md"))


def test_list_after_install(run, workdir):
    """CATCHES: a list that does not report an installed copy as up-to-date, or that prints the skill
    descriptions or the state table differently."""
    run(["skill", "install", "-dir", "dest"])
    r = run(["skill", "list", "-dir", "dest"])
    assert_run_golden(__file__, "list_up_to_date", r, workdir)


def test_list_before_install(run, workdir):
    """CATCHES: a list that errors or omits rows when nothing is installed; each destination is missing."""
    r = run(["skill", "list", "-dir", "dest"])
    assert_run_golden(__file__, "list_missing", r, workdir)


def test_install_twice_skips(run, workdir):
    """CATCHES: a second install that rewrites up-to-date skills instead of skipping them."""
    run(["skill", "install", "-dir", "dest"])
    r = run(["skill", "install", "-dir", "dest"])
    assert_run_golden(__file__, "install_again", r, workdir)


def test_modified_skill_is_refused(run, workdir):
    """CATCHES: an install that overwrites a skill edited after installing; it must skip it, list the
    path as modified in the refusal, suggest --force and exit 1, leaving the edit in place."""
    run(["skill", "install", "-dir", "dest"])
    md = workdir / "dest/declscope-authoring/SKILL.md"
    md.write_text(md.read_text() + "local edit\n")
    listed = run(["skill", "list", "-dir", "dest"])
    r = run(["skill", "install", "-dir", "dest"])
    assert_run_golden(__file__, "list_modified", listed, workdir)
    assert_run_golden(__file__, "install_modified", r, workdir)
    assert md.read_text().endswith("local edit\n")


def test_force_overwrites_modified(run, workdir):
    """CATCHES: -force that does not overwrite an edited skill, or that does not report every skill as
    updated."""
    run(["skill", "install", "-dir", "dest"])
    md = workdir / "dest/declscope-authoring/SKILL.md"
    md.write_text(md.read_text() + "local edit\n")
    r = run(["skill", "install", "-dir", "dest", "-force"])
    assert_run_golden(__file__, "install_force", r, workdir)
    assert_golden(__file__, "authoring_skill_md", installed(md))


def test_short_f_overwrites_modified(run, workdir):
    """CATCHES: an implementation without the -f shorthand for -force."""
    run(["skill", "install", "-dir", "dest"])
    md = workdir / "dest/declscope-authoring/SKILL.md"
    md.write_text("edited\n")
    r = run(["skill", "install", "-f", "-dir", "dest"])
    assert_run_golden(__file__, "install_force", r, workdir)
    assert_golden(__file__, "authoring_skill_md", installed(md))


def test_foreign_skill_is_refused(run, tree, workdir):
    """CATCHES: an install that overwrites a same-named skill another tool wrote; list shows it as foreign,
    install installs the other skill but refuses that one and exits 1."""
    tree({"dest/declscope-authoring/SKILL.md": "---\nname: declscope-authoring\n---\nmine\n"})
    listed = run(["skill", "list", "-dir", "dest"])
    r = run(["skill", "install", "-dir", "dest"])
    assert_run_golden(__file__, "list_foreign", listed, workdir)
    assert_run_golden(__file__, "install_foreign", r, workdir)
    assert (workdir / "dest/declscope-authoring/SKILL.md").read_text() == "---\nname: declscope-authoring\n---\nmine\n"


def test_uninstall_leaves_foreign_skill(run, tree, workdir):
    """CATCHES: an uninstall that deletes a skill this tool did not install."""
    tree({"dest/declscope-authoring/SKILL.md": "---\nname: declscope-authoring\n---\nmine\n"})
    run(["skill", "install", "-dir", "dest"])
    r = run(["skill", "uninstall", "-dir", "dest"])
    assert_run_golden(__file__, "uninstall_foreign", r, workdir)
    assert sorted(p.name for p in (workdir / "dest").iterdir()) == ["declscope-authoring"]


def test_uninstall_dry_run_keeps_files(run, workdir):
    """CATCHES: -dry-run on uninstall that deletes anything, or does not prefix actions with 'would be'."""
    run(["skill", "install", "-dir", "dest"])
    r = run(["skill", "uninstall", "-dir", "dest", "-dry-run"])
    assert_run_golden(__file__, "uninstall_dry_run", r, workdir)
    assert sorted(p.name for p in (workdir / "dest").iterdir()) == ["declscope-adoption", "declscope-authoring"]


def test_uninstall_removes(run, workdir):
    """CATCHES: an uninstall that leaves the skill directories behind or reports them differently."""
    run(["skill", "install", "-dir", "dest"])
    r = run(["skill", "uninstall", "-dir", "dest"])
    assert_run_golden(__file__, "uninstall", r, workdir)
    assert list((workdir / "dest").iterdir()) == []


def test_uninstall_nothing_installed(run, workdir):
    """CATCHES: an uninstall that fails when nothing is installed; each skill is skipped as not installed."""
    r = run(["skill", "uninstall", "-dir", "dest"])
    assert_run_golden(__file__, "uninstall_nothing", r, workdir)


def test_install_named_skill_only(run, workdir):
    """CATCHES: an install that ignores skill name arguments and installs every embedded skill."""
    r = run(["skill", "install", "-dir", "dest", "declscope-adoption"])
    assert_run_golden(__file__, "install_named", r, workdir)
    assert sorted(p.name for p in (workdir / "dest").iterdir()) == ["declscope-adoption"]


def test_list_named_skill_only(run, workdir):
    """CATCHES: a list that ignores the skill name argument and describes every skill."""
    r = run(["skill", "list", "-dir", "dest", "declscope-authoring"])
    assert_run_golden(__file__, "list_named", r, workdir)


def test_install_unknown_skill(run, workdir):
    """CATCHES: an unknown skill name that is ignored instead of refused with the embedded names listed."""
    r = run(["skill", "install", "-dir", "dest", "nosuch"])
    assert_run_golden(__file__, "unknown_skill", r, workdir)
    assert not (workdir / "dest").exists()


def test_dry_run_project_default_agents(run, workdir):
    """CATCHES: a project-scope install with no agent directory present that does not fall back to every
    agent, names the wrong directories (.agents/skills shared by five agents, .claude/skills for Claude
    Code), omits the project root line, or writes anything under -dry-run."""
    (workdir / ".git").mkdir()
    r = run(["skill", "install", "-dry-run"])
    assert_run_golden(__file__, "dry_run_default", r, workdir)
    assert sorted(p.name for p in workdir.iterdir()) == [".git"]


def test_install_project_writes_both_directories(run, workdir):
    """CATCHES: a project-scope install that writes only one of the agent directories."""
    (workdir / ".git").mkdir()
    r = run(["skill", "install"])
    assert_run_golden(__file__, "install_project", r, workdir)
    assert_golden(__file__, "authoring_skill_md", installed(workdir / ".claude/skills/declscope-authoring/SKILL.md"))
    assert_golden(__file__, "authoring_skill_md", installed(workdir / ".agents/skills/declscope-authoring/SKILL.md"))


def test_detected_agent_directory(run, workdir):
    """CATCHES: the default 'detected' agent selection installing for every agent although one agent's
    directory already exists; only .claude is targeted when only .claude is present."""
    (workdir / ".git").mkdir()
    (workdir / ".claude").mkdir()
    r = run(["skill", "install", "-dry-run"])
    assert_run_golden(__file__, "dry_run_detected", r, workdir)


def test_project_root_found_from_subdirectory(run, workdir):
    """CATCHES: a project root search that stops at the working directory instead of walking up, within the
    repository, to the directory holding an agent marker."""
    (workdir / ".git").mkdir()
    (workdir / ".agents").mkdir()
    (workdir / "pkg/deep").mkdir(parents=True)
    r = run(["skill", "list"], cwd=workdir / "pkg/deep")
    assert_run_golden(__file__, "list_from_subdir", r, workdir)


def test_project_root_without_repository(run, workdir):
    """CATCHES: a root search that walks above the working directory when no repository bounds it."""
    (workdir / ".claude").mkdir()
    (workdir / "sub").mkdir()
    r = run(["skill", "list"], cwd=workdir / "sub")
    assert_run_golden(__file__, "list_no_repo", r, workdir)


def test_agent_selection_by_name(run, workdir):
    """CATCHES: -agent claude-code that also targets the shared .agents directory."""
    (workdir / ".git").mkdir()
    r = run(["skill", "list", "-agent", "claude-code"])
    assert_run_golden(__file__, "list_claude", r, workdir)


def test_agent_comma_list_and_dedup(run, workdir):
    """CATCHES: a comma-separated -agent list that is not split, or agents sharing .agents/skills that are
    listed twice."""
    (workdir / ".git").mkdir()
    r = run(["skill", "install", "-dry-run", "-agent", "cursor,codex", "declscope-authoring"])
    assert_run_golden(__file__, "dry_run_shared", r, workdir)


def test_agent_repeated_flag(run, workdir):
    """CATCHES: a repeated -agent flag where only the last value counts."""
    (workdir / ".git").mkdir()
    r = run(["skill", "install", "-dry-run", "-agent", "gemini", "-agent", "claude-code"])
    assert_run_golden(__file__, "dry_run_repeated", r, workdir)


def test_agent_all(run, workdir):
    """CATCHES: -agent all that does not expand to every agent's directory."""
    (workdir / ".git").mkdir()
    (workdir / ".claude").mkdir()
    r = run(["skill", "install", "-dry-run", "-agent", "all"])
    assert_run_golden(__file__, "dry_run_default", r, workdir)


def test_unknown_agent(run, workdir):
    """CATCHES: an unknown -agent value that is ignored instead of refused with the sorted agent names."""
    r = run(["skill", "install", "-agent", "bogus"])
    assert_run_golden(__file__, "unknown_agent", r, workdir)


def test_unknown_scope(run, workdir):
    """CATCHES: an unknown -scope value that falls back to project scope."""
    r = run(["skill", "install", "-scope", "global"])
    assert_run_golden(__file__, "unknown_scope", r, workdir)


def test_empty_scope(run, workdir):
    """CATCHES: an empty -scope value treated as the default instead of a flag error with the usage."""
    r = run(["skill", "install", "-scope="])
    assert_run_golden(__file__, "empty_scope", r, workdir)


def test_user_scope_claude(run, workdir):
    """CATCHES: user scope that does not resolve Claude Code's directory under $HOME/.claude/skills, or that
    prints a project root line for a user-scope run."""
    env = home_env(workdir)
    r = run(["skill", "install", "-agent", "claude-code", "-scope", "user"], env_overrides=env)
    assert_run_golden(__file__, "user_claude", r, workdir)
    assert_golden(__file__, "authoring_skill_md", installed(workdir / "home/.claude/skills/declscope-authoring/SKILL.md"))


def test_user_scope_claude_config_dir(run, workdir):
    """CATCHES: user scope that ignores CLAUDE_CONFIG_DIR, or that uses the whole colon-separated value
    instead of its first entry."""
    env = {**home_env(workdir), "CLAUDE_CONFIG_DIR": f"{workdir}/cc:{workdir}/other"}
    r = run(["skill", "install", "-agent", "claude-code", "-scope", "user", "-dry-run"], env_overrides=env)
    assert_run_golden(__file__, "user_claude_config_dir", r, workdir)


def test_user_scope_other_agents(run, workdir):
    """CATCHES: wrong per-agent user directories: Copilot ~/.copilot, Cursor ~/.cursor, Codex ~/.codex,
    Gemini ~/.gemini and Antigravity ~/.gemini/antigravity, each under skills."""
    env = home_env(workdir)
    r = run(["skill", "install", "-agent", "all", "-scope", "user", "-dry-run", "declscope-authoring"],
            env_overrides=env)
    assert_run_golden(__file__, "user_all", r, workdir)


def test_project_scope_in_home_is_refused(run, workdir):
    """CATCHES: a project install whose root resolves to the home directory, which would put skills in
    front of every project; it is refused with advice to use --scope user or --dir."""
    r = run(["skill", "install"], env_overrides={"HOME": str(workdir)})
    assert_run_golden(__file__, "project_is_home", r, workdir)


def test_dir_overrides_agent_and_scope(run, workdir):
    """CATCHES: -dir that is combined with -agent or -scope instead of overriding them."""
    env = home_env(workdir)
    r = run(["skill", "install", "-dir", "dest", "-agent", "claude-code", "-scope", "user"], env_overrides=env)
    assert_run_golden(__file__, "install_dir", r, workdir)
    assert not (workdir / "home/.claude").exists()


def test_list_alias_ls(run, workdir):
    """CATCHES: a missing ls alias for list."""
    run(["skill", "install", "-dir", "dest"])
    r = run(["skill", "ls", "-dir", "dest"])
    assert_run_golden(__file__, "list_up_to_date", r, workdir)


def test_uninstall_alias_remove(run, workdir):
    """CATCHES: a missing remove alias for uninstall."""
    run(["skill", "install", "-dir", "dest"])
    r = run(["skill", "remove", "-dir", "dest"])
    assert_run_golden(__file__, "uninstall", r, workdir)


def test_dry_run_install_after_partial(run, workdir):
    """CATCHES: a dry run that does not distinguish an up-to-date skill (would be skipped) from a missing
    one (would be installed)."""
    run(["skill", "install", "-dir", "dest", "declscope-adoption"])
    r = run(["skill", "install", "-dir", "dest", "-dry-run"])
    assert_run_golden(__file__, "dry_run_partial", r, workdir)
    assert normalize(r.stdout, workdir).count("would be") == 2
