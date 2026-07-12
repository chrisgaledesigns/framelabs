"""Tests for OnionSkinSettings -- pure data/logic, no mocking needed."""

import pytest

from framelabs.timeline.onion_skin import OnionSkinSettings


def test_defaults():
    settings = OnionSkinSettings()
    assert settings.enabled is False
    assert settings.opacity == 0.35
    assert settings.previous_count == 2
    assert settings.next_count == 1
    assert settings.previous_tint == "#3399ff"
    assert settings.next_tint == "#ff3333"


def test_opacity_for_distance_one_returns_base_opacity():
    settings = OnionSkinSettings(opacity=0.4)
    assert settings.opacity_for_distance(1) == pytest.approx(0.4)


def test_opacity_for_distance_halves_each_step():
    settings = OnionSkinSettings(opacity=0.4)
    assert settings.opacity_for_distance(2) == pytest.approx(0.2)
    assert settings.opacity_for_distance(3) == pytest.approx(0.1)


def test_opacity_for_distance_zero_raises():
    settings = OnionSkinSettings()
    with pytest.raises(ValueError):
        settings.opacity_for_distance(0)


def test_opacity_for_distance_negative_raises():
    settings = OnionSkinSettings()
    with pytest.raises(ValueError):
        settings.opacity_for_distance(-1)


def test_settings_are_independently_mutable():
    a = OnionSkinSettings()
    b = OnionSkinSettings()
    a.opacity = 0.9
    assert b.opacity == 0.35
