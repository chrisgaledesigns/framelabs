"""Tests for InspectorPanel in ui/inspector_panel.py.

A real QWidget is instantiated -- InspectorPanel's whole job is laying
out and exposing a handful of fields, so there's nothing meaningful to
mock. These tests check the built widget's structure (field types,
enabled/disabled state, placeholder text) and its two small public
methods, matching how the module docstring describes each field's
intended behavior.
"""

from framelabs.ui.histogram_widget import HistogramWidget
from framelabs.ui.inspector_panel import InspectorPanel


def test_camera_field_is_editable_read_only_with_placeholder():
    """The Camera field doubles as a live connection-status display --
    read-only (never user-typed) but not disabled/grayed like the
    not-yet-implemented fields."""
    panel = InspectorPanel()

    assert panel.camera_field.isReadOnly() is True
    assert panel.camera_field.isEnabled() is True
    assert panel.camera_field.placeholderText() == "No camera connected"


def test_lens_field_is_read_only_with_na_placeholder():
    """Lens has no real backend data yet either, but per the module
    docstring is read-only rather than disabled."""
    panel = InspectorPanel()

    assert panel.lens_field.isReadOnly() is True
    assert panel.lens_field.placeholderText() == "N/A"


def test_unavailable_fields_are_disabled_with_webcam_placeholder():
    """ISO/Shutter/Aperture/White Balance/Focus have no webcam backend
    support -- each should be genuinely disabled, not just styled to
    look inactive, with placeholder text explaining why."""
    panel = InspectorPanel()

    for field in (
        panel.iso_field,
        panel.shutter_field,
        panel.aperture_field,
        panel.white_balance_field,
        panel.focus_field,
    ):
        assert field.isEnabled() is False
        assert field.placeholderText() == "Unavailable (webcam)"


def test_capture_format_combo_has_only_png():
    """Capture Format is a real, settable field for the webcam-only
    alpha, but PNG is currently the only supported option."""
    panel = InspectorPanel()

    assert panel.capture_format_combo.count() == 1
    assert panel.capture_format_combo.itemText(0) == "PNG"


def test_resolution_field_has_example_placeholder():
    """Resolution is a real, settable field -- not disabled -- with an
    example placeholder rather than a fixed default value."""
    panel = InspectorPanel()

    assert panel.resolution_field.isEnabled() is True
    assert panel.resolution_field.placeholderText() == "e.g. 1920x1080"


def test_histogram_widget_is_a_real_histogram_widget_instance():
    """The Histogram row should hold a real HistogramWidget, so
    MainWindow's histogram_ready connection has something to update."""
    panel = InspectorPanel()

    assert isinstance(panel.histogram_widget, HistogramWidget)


def test_object_name_is_inspector_panel():
    """The panel sets its own object name, used by the app-wide
    stylesheet to target it specifically."""
    panel = InspectorPanel()

    assert panel.objectName() == "inspectorPanel"


def test_set_camera_status_updates_field_text():
    """set_camera_status() should write the given text into the Camera
    field verbatim -- e.g. '{device} Connected' from CameraController."""
    panel = InspectorPanel()

    panel.set_camera_status("Webcam (device 0) Connected")

    assert panel.camera_field.text() == "Webcam (device 0) Connected"


def test_clear_camera_status_clears_field_back_to_placeholder():
    """clear_camera_status() should empty the field, so the
    'No camera connected' placeholder shows again."""
    panel = InspectorPanel()
    panel.set_camera_status("Webcam (device 0) Connected")

    panel.clear_camera_status()

    assert panel.camera_field.text() == ""
