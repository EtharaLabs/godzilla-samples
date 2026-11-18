"""declscope skill: installing, listing and removing the agent skills the binary embeds."""

import re

from conftest import GO_MOD, read_golden, snapshot_tree, write_tree


def golden(name):
    return read_golden(__file__, name)


STAMP = re.compile(r'^x-embedded-at: "\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ"$', re.M)


def tree_without_clock(root):
    """The installed files, with the install time (the one volatile line) masked."""
    return STAMP.sub('x-embedded-at: "<install time>"', snapshot_tree(root))


def test_install_into_a_directory(ds, workdir):
    """CATCHES: a skill install that writes different files or content (front matter, embedded version and
    digest, the skill text), reports them differently, or writes anything under --dry-run."""
    write_tree(workdir, {"go.mod": GO_MOD})
    dry = ds(["skill", "install", "-dir", "out", "-dry-run"])
    nothing = snapshot_tree(workdir)
    real = ds(["skill", "install", "-dir", "out"])
    assert "\n".join([dry.transcript, nothing, real.transcript, tree_without_clock(workdir)]) == golden(
        "install_dir")


def test_reinstall_skips_and_force_updates(ds, workdir):
    """CATCHES: a skill install that rewrites skills already up to date, or a -f that does not update the one
    skill it names."""
    write_tree(workdir, {"go.mod": GO_MOD})
    first = ds(["skill", "install", "-dir", "out"])
    again = ds(["skill", "install", "-dir", "out"])
    forced = ds(["skill", "install", "-dir", "out", "-f", "declscope-adoption"])
    assert "\n".join([first.transcript, again.transcript, forced.transcript]) == golden("reinstall")


def test_list_and_uninstall(ds, workdir):
    """CATCHES: a skill list that reports a different state per skill (missing, up-to-date) or path, or an
    uninstall that removes a skill it was not asked to."""
    write_tree(workdir, {"go.mod": GO_MOD})
    before = ds(["skill", "list", "-dir", "out"])
    ds(["skill", "install", "-dir", "out"])
    installed = ds(["skill", "list", "-dir", "out"])
    removed = ds(["skill", "uninstall", "-dir", "out", "declscope-adoption"])
    after = ds(["skill", "list", "-dir", "out"])
    assert "\n".join([before.transcript, installed.transcript, removed.transcript, after.transcript,
                      tree_without_clock(workdir)]) == golden("list_and_uninstall")


def test_install_for_an_agent_in_the_project(ds, workdir):
    """CATCHES: a skill install --agent claude-code that writes anywhere but the project's .claude/skills, or a
    list over every agent that names different directories."""
    write_tree(workdir, {"go.mod": GO_MOD})
    install = ds(["skill", "install", "--agent", "claude-code"])
    listing = ds(["skill", "list", "--agent", "all"])
    assert "\n".join([install.transcript, listing.transcript, tree_without_clock(workdir)]) == golden(
        "install_agent")


def test_unknown_skill_and_agent(ds, workdir):
    """CATCHES: a skill install that accepts a skill name or an agent it does not carry instead of refusing."""
    write_tree(workdir, {"go.mod": GO_MOD})
    skill = ds(["skill", "install", "-dir", "out", "declscope-nothing"])
    agent = ds(["skill", "install", "--agent", "notepad"])
    assert "\n".join([skill.transcript, agent.transcript, snapshot_tree(workdir)]) == golden("unknown_names")
