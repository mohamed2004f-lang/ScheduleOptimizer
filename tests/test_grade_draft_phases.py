"""Tests for partial/final grade draft phase totals."""
from backend.services.grades import _compute_total_for_phase


def test_compute_total_partial_phase():
    assert _compute_total_for_phase("partial", 10, 25, None) == 35
    assert _compute_total_for_phase("partial", None, 20, 60) == 20


def test_compute_total_final_phase():
    assert _compute_total_for_phase("final", 10, 25, 50) == 85
    assert _compute_total_for_phase("final", 10, 25, None) == 35


def test_compute_total_combined_phase():
    assert _compute_total_for_phase("combined", 10, 25, 50) == 85
