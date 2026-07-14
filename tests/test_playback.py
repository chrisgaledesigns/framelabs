"""Tests for framelabs.timeline.playback.PlaybackSettings."""

import pytest

from framelabs.timeline.playback import PlaybackSettings


def test_defaults():
    settings = PlaybackSettings()
    assert settings.is_playing is False
    assert settings.speed_percent == 100
    assert settings.loop is False


def test_interval_ms_at_100_percent_matches_base_interval():
    settings = PlaybackSettings(speed_percent=100)
    # 12 fps -> ~83ms/frame at native speed.
    assert settings.interval_ms(12) == round(1000 / 12)


def test_interval_ms_at_200_percent_is_half_the_base_interval():
    settings = PlaybackSettings(speed_percent=200)
    assert settings.interval_ms(12) == round((1000 / 12) / 2)


def test_interval_ms_at_50_percent_is_double_the_base_interval():
    settings = PlaybackSettings(speed_percent=50)
    assert settings.interval_ms(12) == round((1000 / 12) * 2)


def test_interval_ms_at_25_percent_is_four_times_the_base_interval():
    settings = PlaybackSettings(speed_percent=25)
    assert settings.interval_ms(12) == round((1000 / 12) * 4)


def test_interval_ms_zero_fps_raises():
    settings = PlaybackSettings()
    with pytest.raises(ValueError):
        settings.interval_ms(0)


def test_interval_ms_negative_fps_raises():
    settings = PlaybackSettings()
    with pytest.raises(ValueError):
        settings.interval_ms(-12)


def test_settings_are_independently_mutable():
    a = PlaybackSettings()
    b = PlaybackSettings()
    a.speed_percent = 200
    a.loop = True
    assert b.speed_percent == 100
    assert b.loop is False
