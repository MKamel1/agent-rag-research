"""Tests for `app.adaptive_batch_sizer.AdaptiveBatchSizer` (T-DOC21) -- offline, fake VRAM probe
throughout, no real nvidia-smi/GPU calls.
"""

from app.adaptive_batch_sizer import AdaptiveBatchSizer


def _probe(*values):
    """A fake vram_probe that yields each value in `values` in order, then repeats the last."""
    it = iter(values)
    last = [None]

    def _next():
        try:
            last[0] = next(it)
        except StopIteration:
            pass
        return last[0]

    return _next


def test_holds_steady_in_the_comfortable_zone_between_margin_and_growth_threshold():
    # margin=1000, growth_threshold defaults to 2*margin=2000 -- 1500 is strictly between.
    sizer = AdaptiveBatchSizer(
        initial_size=4, safety_margin_mib=1000, vram_probe=_probe(1500, 1500, 1500)
    )
    assert sizer.next_size() == 4
    assert sizer.next_size() == 4
    assert sizer.next_size() == 4


def test_grows_by_growth_step_when_free_vram_clears_the_growth_threshold():
    sizer = AdaptiveBatchSizer(
        initial_size=4,
        safety_margin_mib=1000,
        growth_step=4,
        vram_probe=_probe(3000, 3000, 3000),
    )
    assert sizer.next_size() == 8
    assert sizer.next_size() == 12
    assert sizer.next_size() == 16


def test_shrinks_by_half_when_free_vram_is_at_or_below_the_safety_margin():
    sizer = AdaptiveBatchSizer(
        initial_size=16, safety_margin_mib=1000, vram_probe=_probe(1000, 500, 100)
    )
    assert sizer.next_size() == 8
    assert sizer.next_size() == 4
    assert sizer.next_size() == 2


def test_shrink_floors_at_min_size():
    sizer = AdaptiveBatchSizer(
        initial_size=2, min_size=1, safety_margin_mib=1000, vram_probe=_probe(0, 0, 0)
    )
    assert sizer.next_size() == 1
    assert sizer.next_size() == 1  # already at floor, stays there


def test_growth_ceilings_at_max_size_independent_of_how_much_vram_is_free():
    sizer = AdaptiveBatchSizer(
        initial_size=60,
        max_size=64,
        growth_step=4,
        safety_margin_mib=1000,
        vram_probe=_probe(999_999, 999_999),  # comically abundant free VRAM
    )
    assert sizer.next_size() == 64
    assert sizer.next_size() == 64  # capped, doesn't keep climbing


def test_holds_current_size_when_the_vram_probe_returns_none():
    sizer = AdaptiveBatchSizer(initial_size=4, vram_probe=_probe(None, None))
    assert sizer.next_size() == 4
    assert sizer.next_size() == 4


def test_never_grows_blind_after_a_probe_failure_even_if_a_later_reading_would_have_grown():
    # A None reading holds steady; it must not "bank" a missed growth opportunity.
    sizer = AdaptiveBatchSizer(
        initial_size=4, safety_margin_mib=1000, vram_probe=_probe(None, 3000)
    )
    assert sizer.next_size() == 4  # probe unavailable -> hold
    assert sizer.next_size() == 8  # next call: real reading, one normal growth step


def test_growth_threshold_defaults_to_twice_the_safety_margin():
    # free=1500 is above margin=1000 but below default growth_threshold=2000 -> hold, not grow.
    sizer = AdaptiveBatchSizer(initial_size=4, safety_margin_mib=1000, vram_probe=_probe(1500))
    assert sizer.next_size() == 4


def test_explicit_growth_threshold_overrides_the_default():
    sizer = AdaptiveBatchSizer(
        initial_size=4,
        safety_margin_mib=1000,
        growth_threshold_mib=1200,  # lower than the 2x-margin default
        vram_probe=_probe(1500),
    )
    assert sizer.next_size() == 8  # 1500 clears the explicit (lower) threshold now


def test_rejects_initial_size_below_min_size():
    import pytest

    with pytest.raises(ValueError):
        AdaptiveBatchSizer(initial_size=0, min_size=1)


def test_rejects_initial_size_above_max_size():
    import pytest

    with pytest.raises(ValueError):
        AdaptiveBatchSizer(initial_size=100, max_size=64)


def test_default_vram_probe_is_the_real_free_vram_mib():
    from app.gpu_headroom import free_vram_mib

    sizer = AdaptiveBatchSizer(initial_size=4)
    assert sizer._vram_probe is free_vram_mib
