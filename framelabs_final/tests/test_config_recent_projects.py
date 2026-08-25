"""Tests for Config's recent-projects tracking (get_recent_projects,
add_recent_project), used by the startup Welcome dialog.
"""

from framelabs.core.config import MAX_RECENT_PROJECTS, Config


def test_no_recent_projects_by_default(tmp_path):
    cfg = Config(config_path=tmp_path / "config.json")
    assert cfg.get_recent_projects() == []


def test_add_recent_project_appears_first(tmp_path):
    cfg = Config(config_path=tmp_path / "config.json")
    project_dir = tmp_path / "Robot Walk"
    project_dir.mkdir()

    cfg.add_recent_project(project_dir, "Robot Walk")

    recents = cfg.get_recent_projects()
    assert recents == [{"path": str(project_dir), "name": "Robot Walk"}]


def test_reopening_moves_project_to_front_without_duplicating(tmp_path):
    cfg = Config(config_path=tmp_path / "config.json")
    project_a = tmp_path / "A"
    project_b = tmp_path / "B"
    project_a.mkdir()
    project_b.mkdir()

    cfg.add_recent_project(project_a, "A")
    cfg.add_recent_project(project_b, "B")
    cfg.add_recent_project(project_a, "A")

    recents = cfg.get_recent_projects()
    assert [entry["path"] for entry in recents] == [str(project_a), str(project_b)]


def test_recent_projects_list_is_capped(tmp_path):
    cfg = Config(config_path=tmp_path / "config.json")

    for i in range(MAX_RECENT_PROJECTS + 5):
        project_dir = tmp_path / f"project_{i}"
        project_dir.mkdir()
        cfg.add_recent_project(project_dir, f"Project {i}")

    assert len(cfg.get_recent_projects()) == MAX_RECENT_PROJECTS
    # Most recently added should be first.
    newest_dir = tmp_path / f"project_{MAX_RECENT_PROJECTS + 4}"
    assert cfg.get_recent_projects()[0]["path"] == str(newest_dir)


def test_missing_project_folder_is_pruned_on_read(tmp_path):
    cfg = Config(config_path=tmp_path / "config.json")
    real_dir = tmp_path / "Real"
    real_dir.mkdir()
    missing_dir = tmp_path / "Deleted"  # never created on disk

    cfg.add_recent_project(missing_dir, "Deleted")
    cfg.add_recent_project(real_dir, "Real")

    recents = cfg.get_recent_projects()
    assert [entry["path"] for entry in recents] == [str(real_dir)]


def test_pruning_stale_entries_persists_across_reload(tmp_path):
    config_path = tmp_path / "config.json"
    cfg = Config(config_path=config_path)
    missing_dir = tmp_path / "Deleted"
    cfg.add_recent_project(missing_dir, "Deleted")
    cfg.save()
    cfg.get_recent_projects()  # triggers the prune-and-save

    reloaded = Config(config_path=config_path)
    assert reloaded.get_recent_projects() == []


def test_add_recent_project_does_not_autosave(tmp_path):
    """add_recent_project() is documented as not calling save() itself --
    callers (MainWindow._adopt_project) persist it alongside other
    state. Reloading without an explicit save() should not see it."""
    config_path = tmp_path / "config.json"
    cfg = Config(config_path=config_path)
    project_dir = tmp_path / "Robot Walk"
    project_dir.mkdir()

    cfg.add_recent_project(project_dir, "Robot Walk")
    # deliberately no cfg.save() here

    reloaded = Config(config_path=config_path)
    assert reloaded.get_recent_projects() == []
