"""Deterministic VOX timing tests: timestamps are synthetic, with no sleeps."""
import pytest


def test_activation_requires_consecutive_loud_blocks(vox):
    trigger = vox.VoxTrigger(activation_time=1)
    assert not trigger.update(12, 0.5, 0.5)
    assert not trigger.update(11.9, 0.5, 1)
    assert trigger.loud_duration == 0
    assert not trigger.update(12, 0.5, 1.5)
    assert trigger.update(12, 0.5, 2)
    assert trigger.transmitting
    assert trigger.activation_time_stamp == 2
    assert trigger.loud_duration == 0


def test_hysteresis_refreshes_activity_at_release_threshold(vox):
    trigger = vox.VoxTrigger(hang_time=3, min_transmission_time=0)
    trigger.activate(0)
    # 9 dB is below activation (12), but exactly at release (12 - 3).
    assert not trigger.update(9, 0.5, 2)
    assert trigger.last_activity_time == 2
    assert not trigger.update(8.9, 0.5, 4.9)
    assert trigger.update(8.9, 0.5, 5)
    assert not trigger.transmitting


def test_minimum_transmission_outlasts_hang_time(vox):
    trigger = vox.VoxTrigger(hang_time=2, min_transmission_time=10)
    trigger.activate(0)
    assert not trigger.update(0, 0.5, 2)
    assert not trigger.update(0, 0.5, 9.9)
    assert trigger.update(0, 0.5, 10)
    assert not trigger.transmitting


def test_maximum_transmission_stops_even_with_continuous_activity(vox):
    trigger = vox.VoxTrigger(max_transmission_time=5)
    trigger.activate(0)
    assert not trigger.update(20, 0.5, 4.9)
    assert trigger.update(20, 0.5, 5)
    assert not trigger.transmitting


@pytest.mark.parametrize('maximum', [0, -1])
def test_nonpositive_maximum_disables_time_limit(vox, maximum):
    trigger = vox.VoxTrigger(max_transmission_time=maximum)
    trigger.activate(0)
    assert not trigger.update(20, 0.5, 1000)
    assert trigger.transmitting


def test_new_activation_after_release_needs_full_loud_duration(vox):
    trigger = vox.VoxTrigger(activation_time=1, hang_time=1,
                             min_transmission_time=0)
    assert trigger.update(12, 1, 1)
    assert trigger.update(0, 0.5, 2)
    assert not trigger.update(12, 0.5, 2.5)
    assert trigger.update(12, 0.5, 3)
    assert trigger.activation_time_stamp == 3
