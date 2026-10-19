"""Smoke test verifying imports."""

import crewai

import supplychain


def test_imports():
    assert crewai is not None
    assert supplychain is not None
