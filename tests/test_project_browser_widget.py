"""Tests for ProjectBrowserWidget (backlog item #3).

Uses real Project/Frame objects, real generated JPEG thumbnails written to
tmp_path (via cv2, matching test_timeline_widget.py's existing convention
for anything reading real thumbnail files), and real tmp_path folders for
the Exports scan -- matching this repo's existing convention of testing
real behavior rather than mocking the thing actually being tested.
"""

from pathlib import Path

import cv2
import numpy as np

from framelabs.project.project import Frame, Project
from framelabs.ui.project_browser_widget import FRAME_TILE_SIZE, ProjectBrowserWidget


def _make_project(tmp_path: Path, frames: list[Frame]) -> Project:
    project_path = tmp_path / "MyFilm"
    project_path.mkdir()
    return Project(
        version=2,
        name="MyFilm",
        fps=12,
        resolution=(1920, 1080),
        camera_model=None,
        camera_lens=None,
        frames=frames,
        project_path=project_path,
    )


def _write_real_thumbnail(project: Project, frame_number: int) -> None:
    """Write a real, tiny readable JPEG at the exact path/name TimelineWidget
    and ProjectBrowserWidget both expect: thumbnails/{number:06d}.jpg.
    """
    thumbnails_dir = project.project_path / "thumbnails"
    thumbnails_dir.mkdir(exist_ok=True)
    image = np.zeros((20, 20, 3), dtype=np.uint8)
    cv2.imwrite(str(thumbnails_dir / f"{frame_number:06d}.jpg"), image)


def _frames_grid_labels(widget: ProjectBrowserWidget) -> list[str]:
    grid = widget._frames_grid
    return [grid.item(i).text() for i in range(grid.count())]


def _notes_list_labels(widget: ProjectBrowserWidget) -> list[str]:
    notes = widget._notes_list
    return [notes.item(i).text() for i in range(notes.count())]


def _exports_list_labels(widget: ProjectBrowserWidget) -> list[str]:
    exports = widget._exports_list
    return [exports.item(i).text() for i in range(exports.count())]


def test_no_project_shows_placeholder_and_hides_all_sections(qtbot):
    widget = ProjectBrowserWidget()
    qtbot.addWidget(widget)

    assert not widget._no_project_label.isHidden()
    for section in widget._section_widgets():
        assert section.isHidden()


def test_set_project_shows_all_three_sections_hides_placeholder(qtbot, tmp_path):
    widget = ProjectBrowserWidget()
    qtbot.addWidget(widget)
    project = _make_project(tmp_path, [Frame(number=1, file="images/000001.png")])

    widget.set_project(project)

    assert widget._no_project_label.isHidden()
    for section in widget._section_widgets():
        assert not section.isHidden()


def test_frames_grid_has_one_tile_per_frame_in_order(qtbot, tmp_path):
    widget = ProjectBrowserWidget()
    qtbot.addWidget(widget)
    project = _make_project(
        tmp_path,
        [
            Frame(number=1, file="images/000001.png"),
            Frame(number=2, file="images/000002.png"),
            Frame(number=3, file="images/000003.png"),
        ],
    )

    widget.set_project(project)

    assert _frames_grid_labels(widget) == ["1", "2", "3"]


def test_frames_grid_sorts_by_number_matching_timeline_frames(qtbot, tmp_path):
    """Emitted indices must line up with Timeline.frames, which is always
    sorted by frame number regardless of Project.frames' insertion order --
    see Timeline.frames' docstring. A project whose frame list is out of
    number order (e.g. loaded from an older/edited project.ffproj) must
    still produce the same order here.
    """
    widget = ProjectBrowserWidget()
    qtbot.addWidget(widget)
    project = _make_project(
        tmp_path,
        [
            Frame(number=3, file="images/000003.png"),
            Frame(number=1, file="images/000001.png"),
            Frame(number=2, file="images/000002.png"),
        ],
    )

    widget.set_project(project)

    assert _frames_grid_labels(widget) == ["1", "2", "3"]


def test_frames_grid_shows_real_thumbnail_icon_when_file_exists(qtbot, tmp_path):
    widget = ProjectBrowserWidget()
    qtbot.addWidget(widget)
    project = _make_project(tmp_path, [Frame(number=1, file="images/000001.png")])
    _write_real_thumbnail(project, frame_number=1)

    widget.set_project(project)

    icon = widget._frames_grid.item(0).icon()
    assert not icon.isNull()
    pixmap = icon.pixmap(FRAME_TILE_SIZE, FRAME_TILE_SIZE)
    assert not pixmap.isNull()


def test_frames_grid_has_no_icon_when_thumbnail_missing(qtbot, tmp_path):
    widget = ProjectBrowserWidget()
    qtbot.addWidget(widget)
    # Deliberately no thumbnail file written for this frame.
    project = _make_project(tmp_path, [Frame(number=1, file="images/000001.png")])

    widget.set_project(project)

    assert widget._frames_grid.item(0).icon().isNull()


def test_notes_list_only_includes_frames_with_real_notes(qtbot, tmp_path):
    widget = ProjectBrowserWidget()
    qtbot.addWidget(widget)
    project = _make_project(
        tmp_path,
        [
            Frame(number=1, file="images/000001.png", notes=""),
            Frame(number=2, file="images/000002.png", notes="   "),
            Frame(number=3, file="images/000003.png", notes="Puppet's arm needs reset"),
        ],
    )

    widget.set_project(project)

    assert _notes_list_labels(widget) == ["Frame 3: Puppet's arm needs reset"]


def test_exports_list_lists_real_files_in_exports_folder(qtbot, tmp_path):
    widget = ProjectBrowserWidget()
    qtbot.addWidget(widget)
    project = _make_project(tmp_path, [])
    exports_dir = project.project_path / "exports"
    exports_dir.mkdir()
    (exports_dir / "robot_walk.blend").write_text("fake blend contents")
    (exports_dir / "robot_walk_v2.blend").write_text("fake blend contents")

    widget.set_project(project)

    assert sorted(_exports_list_labels(widget)) == [
        "robot_walk.blend",
        "robot_walk_v2.blend",
    ]


def test_exports_list_empty_when_folder_missing(qtbot, tmp_path):
    widget = ProjectBrowserWidget()
    qtbot.addWidget(widget)
    # No exports/ folder created at all -- shouldn't crash.
    project = _make_project(tmp_path, [])

    widget.set_project(project)

    assert _exports_list_labels(widget) == []


def test_double_clicking_frame_tile_emits_frame_selected_with_its_index(
    qtbot, tmp_path
):
    widget = ProjectBrowserWidget()
    qtbot.addWidget(widget)
    project = _make_project(
        tmp_path,
        [
            Frame(number=1, file="images/000001.png"),
            Frame(number=2, file="images/000002.png"),
        ],
    )
    widget.set_project(project)
    second_tile = widget._frames_grid.item(1)

    with qtbot.waitSignal(widget.frame_selected, timeout=1000) as blocker:
        widget._on_indexed_item_double_clicked(second_tile)

    assert blocker.args == [1]


def test_double_clicking_notes_row_emits_frame_selected_with_its_index(qtbot, tmp_path):
    widget = ProjectBrowserWidget()
    qtbot.addWidget(widget)
    project = _make_project(
        tmp_path,
        [
            Frame(number=1, file="images/000001.png", notes=""),
            Frame(number=2, file="images/000002.png", notes="Reset puppet"),
        ],
    )
    widget.set_project(project)
    notes_row = widget._notes_list.item(0)

    with qtbot.waitSignal(widget.frame_selected, timeout=1000) as blocker:
        widget._on_indexed_item_double_clicked(notes_row)

    assert blocker.args == [1]


def test_set_project_none_after_real_project_resets_to_placeholder(qtbot, tmp_path):
    widget = ProjectBrowserWidget()
    qtbot.addWidget(widget)
    project = _make_project(tmp_path, [Frame(number=1, file="images/000001.png")])
    widget.set_project(project)

    widget.set_project(None)

    assert not widget._no_project_label.isHidden()
    for section in widget._section_widgets():
        assert section.isHidden()
    assert _frames_grid_labels(widget) == []
