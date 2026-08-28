"""Tests for InspectorPanel in ui/inspector_panel.py.

A real QWidget is instantiated -- InspectorPanel's whole job is laying
out and exposing a handful of fields, so there's nothing meaningful to
mock. These tests check the built widget's structure (field types,
enabled/disabled state, placeholder text), its public methods, and the
signals it emits on user interaction, matching how the module docstring
describes each field's intended behavior.
"""

from framelabs.ui.histogram_widget import HistogramWidget
from framelabs.ui.inspector_panel import (
    APERTURE_VALUES,
    ISO_VALUES,
    SHUTTER_VALUES,
    InspectorPanel,
)


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


def test_dslr_combos_are_populated_but_disabled_until_a_dslr_connects():
    """ISO/Shutter/Aperture are genuine, preset-populated controls, but
    start disabled -- no camera is connected yet, and even once one is,
    only a real DSLR (not a webcam) should enable them."""
    panel = InspectorPanel()

    assert [panel.iso_field.itemText(i) for i in range(panel.iso_field.count())] == (
        ISO_VALUES
    )
    assert [
        panel.shutter_field.itemText(i) for i in range(panel.shutter_field.count())
    ] == SHUTTER_VALUES
    assert [
        panel.aperture_field.itemText(i) for i in range(panel.aperture_field.count())
    ] == APERTURE_VALUES

    for field in (panel.iso_field, panel.shutter_field, panel.aperture_field):
        assert field.isEnabled() is False


def test_unavailable_fields_are_disabled_with_placeholder():
    """White Balance/Focus have no backend support at all yet (webcam or
    DSLR) -- each should be genuinely disabled, not just styled to look
    inactive, with placeholder text explaining why."""
    panel = InspectorPanel()

    for field in (panel.white_balance_field, panel.focus_field):
        assert field.isEnabled() is False
        assert field.placeholderText() == "Unavailable"


def test_set_dslr_controls_enabled_true_enables_iso_shutter_aperture():
    """set_dslr_controls_enabled(True) should enable exactly the
    ISO/Shutter/Aperture combos, e.g. once CameraController reports a
    "gphoto" backend_type."""
    panel = InspectorPanel()

    panel.set_dslr_controls_enabled(True)

    assert panel.iso_field.isEnabled() is True
    assert panel.shutter_field.isEnabled() is True
    assert panel.aperture_field.isEnabled() is True
    # Unaffected by DSLR state -- still not backed by any implementation.
    assert panel.white_balance_field.isEnabled() is False
    assert panel.focus_field.isEnabled() is False


def test_set_dslr_controls_enabled_false_disables_iso_shutter_aperture():
    """set_dslr_controls_enabled(False) should disable the combos again,
    e.g. on disconnect or when a webcam (not a DSLR) connects."""
    panel = InspectorPanel()
    panel.set_dslr_controls_enabled(True)

    panel.set_dslr_controls_enabled(False)

    assert panel.iso_field.isEnabled() is False
    assert panel.shutter_field.isEnabled() is False
    assert panel.aperture_field.isEnabled() is False


def test_iso_field_activation_emits_iso_changed_as_int():
    """Selecting an ISO value should emit iso_changed with the value
    parsed as an int, since CameraInterface.set_iso() takes an int."""
    panel = InspectorPanel()
    panel.set_dslr_controls_enabled(True)
    received = []
    panel.iso_changed.connect(received.append)

    panel.iso_field.setCurrentIndex(2)  # "400"
    panel._on_iso_activated(2)

    assert received == [400]


def test_shutter_field_activation_emits_shutter_changed_as_text():
    """Selecting a shutter value should emit shutter_changed with the
    combo's text verbatim (e.g. "1/250")."""
    panel = InspectorPanel()
    panel.set_dslr_controls_enabled(True)
    received = []
    panel.shutter_changed.connect(received.append)

    panel.shutter_field.setCurrentIndex(4)  # "1/125"
    panel._on_shutter_activated(4)

    assert received == ["1/125"]


def test_aperture_field_activation_emits_aperture_changed_as_text():
    """Selecting an aperture value should emit aperture_changed with the
    combo's text verbatim (e.g. "f/5.6")."""
    panel = InspectorPanel()
    panel.set_dslr_controls_enabled(True)
    received = []
    panel.aperture_changed.connect(received.append)

    panel.aperture_field.setCurrentIndex(4)  # "f/5.6"
    panel._on_aperture_activated(4)

    assert received == ["f/5.6"]


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
