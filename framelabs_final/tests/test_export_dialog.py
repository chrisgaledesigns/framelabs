"""Tests for ExportDialog in ui/export_dialog.py.

These tests exercise the dialog's own logic (checkbox-driven enabled
state, ExportRequest construction) directly against real widget state --
no mocking, following this suite's existing widget-test convention (see
test_timeline_widget.py's docstring).
"""

from framelabs.export.export_service import ExportRequest
from framelabs.project.creator import create_new_project
from framelabs.ui.export_dialog import ExportDialog


def _make_project(tmp_path, fps=12):
    return create_new_project(
        name="Robot Walk Cycle",
        parent_dir=tmp_path,
        fps=fps,
        resolution=(64, 48),
    )


def test_nothing_checked_by_default(qtbot, tmp_path):
    """Nothing should be checked when the dialog opens -- Chris's
    explicit choice to force a real decision every time rather than
    defaulting to "all three"."""
    dialog = ExportDialog(_make_project(tmp_path))
    qtbot.addWidget(dialog)

    assert not dialog.video_check.isChecked()
    assert not dialog.sequence_check.isChecked()
    assert not dialog.gif_check.isChecked()


def test_export_button_disabled_with_nothing_checked(qtbot, tmp_path):
    dialog = ExportDialog(_make_project(tmp_path))
    qtbot.addWidget(dialog)

    ok_button = dialog.buttons.button(dialog.buttons.StandardButton.Ok)
    assert not ok_button.isEnabled()


def test_export_button_enabled_once_one_format_checked(qtbot, tmp_path):
    dialog = ExportDialog(_make_project(tmp_path))
    qtbot.addWidget(dialog)
    ok_button = dialog.buttons.button(dialog.buttons.StandardButton.Ok)

    dialog.gif_check.setChecked(True)

    assert ok_button.isEnabled()


def test_export_button_disabled_again_once_all_unchecked(qtbot, tmp_path):
    dialog = ExportDialog(_make_project(tmp_path))
    qtbot.addWidget(dialog)
    ok_button = dialog.buttons.button(dialog.buttons.StandardButton.Ok)

    dialog.sequence_check.setChecked(True)
    assert ok_button.isEnabled()
    dialog.sequence_check.setChecked(False)

    assert not ok_button.isEnabled()


def test_codec_combo_disabled_until_video_checked(qtbot, tmp_path):
    dialog = ExportDialog(_make_project(tmp_path))
    qtbot.addWidget(dialog)

    assert not dialog.codec_combo.isEnabled()
    dialog.video_check.setChecked(True)
    assert dialog.codec_combo.isEnabled()


def test_gif_fps_spin_disabled_until_gif_checked(qtbot, tmp_path):
    dialog = ExportDialog(_make_project(tmp_path))
    qtbot.addWidget(dialog)

    assert not dialog.gif_fps_spin.isEnabled()
    dialog.gif_check.setChecked(True)
    assert dialog.gif_fps_spin.isEnabled()


def test_gif_fps_spin_defaults_to_project_fps(qtbot, tmp_path):
    dialog = ExportDialog(_make_project(tmp_path, fps=24))
    qtbot.addWidget(dialog)

    assert dialog.gif_fps_spin.value() == 24.0


def test_export_request_reflects_checked_formats_only(qtbot, tmp_path):
    dialog = ExportDialog(_make_project(tmp_path))
    qtbot.addWidget(dialog)

    dialog.gif_check.setChecked(True)
    request = dialog.export_request()

    assert isinstance(request, ExportRequest)
    assert request.want_gif is True
    assert request.want_video is False
    assert request.want_image_sequence is False


def test_export_request_defaults_to_auto_codec(qtbot, tmp_path):
    dialog = ExportDialog(_make_project(tmp_path))
    qtbot.addWidget(dialog)
    dialog.video_check.setChecked(True)

    request = dialog.export_request()

    assert request.video_codec == "auto"


def test_export_request_reflects_chosen_codec(qtbot, tmp_path):
    dialog = ExportDialog(_make_project(tmp_path))
    qtbot.addWidget(dialog)
    dialog.video_check.setChecked(True)
    dialog.codec_combo.setCurrentIndex(2)  # "MPEG-4 (mp4v)..."

    request = dialog.export_request()

    assert request.video_codec == "mp4v"


def test_export_request_reflects_gif_fps_override(qtbot, tmp_path):
    dialog = ExportDialog(_make_project(tmp_path, fps=12))
    qtbot.addWidget(dialog)
    dialog.gif_check.setChecked(True)
    dialog.gif_fps_spin.setValue(30.0)

    request = dialog.export_request()

    assert request.gif_fps == 30.0
