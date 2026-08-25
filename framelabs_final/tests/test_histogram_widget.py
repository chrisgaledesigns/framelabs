"""Tests for HistogramWidget in ui/histogram_widget.py.

A real QWidget is instantiated (matching this repo's convention for
widget tests, e.g. test_timeline_widget.py) since HistogramWidget's
whole job is painting -- there's nothing meaningful to mock. paintEvent()
is exercised via widget.grab() (renders the widget offscreen and
triggers a real paint pass) rather than calling paintEvent() directly,
so QPainter is always given a real, active paint device -- constructing
a QPainter(self) with no active paint session raises.
"""

import numpy as np

from framelabs.ui.histogram_widget import MIN_HEIGHT, HistogramWidget


def test_init_has_no_histogram_and_minimum_height():
    """A freshly built widget has no histogram data yet, and enforces
    the module's minimum strip height."""
    widget = HistogramWidget()

    assert widget._histogram is None
    assert widget.minimumHeight() == MIN_HEIGHT


def test_size_hint_matches_minimum_height():
    """sizeHint() should suggest a default size consistent with
    MIN_HEIGHT, for layouts that consult it."""
    widget = HistogramWidget()

    hint = widget.sizeHint()

    assert hint.width() == 200
    assert hint.height() == MIN_HEIGHT


def test_update_histogram_stores_data_and_triggers_repaint():
    """update_histogram() should store the array for later painting."""
    widget = HistogramWidget()
    histogram = np.zeros(256, dtype=np.float64)
    histogram[128] = 1.0

    widget.update_histogram(histogram)

    assert widget._histogram is histogram


def test_paint_event_with_no_histogram_does_not_raise():
    """Before any histogram has arrived, painting should just draw the
    background and return -- no crash on the None case."""
    widget = HistogramWidget()
    widget.resize(200, MIN_HEIGHT)

    widget.grab()  # should not raise


def test_paint_event_with_empty_histogram_does_not_raise():
    """An empty (size == 0) histogram array should be treated the same
    as no data at all."""
    widget = HistogramWidget()
    widget.resize(200, MIN_HEIGHT)
    widget.update_histogram(np.array([], dtype=np.float64))

    widget.grab()  # should not raise


def test_paint_event_with_all_zero_histogram_does_not_raise():
    """A histogram whose peak bin is 0 (all-black or all-empty frame)
    must not divide by zero when scaling bar heights."""
    widget = HistogramWidget()
    widget.resize(200, MIN_HEIGHT)
    widget.update_histogram(np.zeros(256, dtype=np.float64))

    widget.grab()  # should not raise


def test_paint_event_with_real_histogram_does_not_raise():
    """A normal, populated histogram should paint without error --
    exercises the actual bar-drawing loop."""
    widget = HistogramWidget()
    widget.resize(200, MIN_HEIGHT)
    histogram = np.linspace(0.0, 1.0, 256)
    widget.update_histogram(histogram)

    widget.grab()  # should not raise
