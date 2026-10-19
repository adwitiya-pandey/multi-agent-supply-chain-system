"""Tests for configuration settings (config.py)."""

import pytest
from pydantic import ValidationError

from supplychain.config import Settings


def test_config_defaults():
    settings = Settings()
    assert settings.llm_mode == "scripted"
    assert settings.gemini_model == "gemini-3.8-flash"
    assert settings.cost_budget_usd == 0.50
    assert settings.service_level == 0.95
    assert settings.senior_po_threshold_usd == 10000.0


def test_secret_never_echoed():
    secret_val = "sensitive-gemini-key-12345"
    settings = Settings(GEMINI_API_KEY=secret_val)
    # Check that plain secret does not appear in str or repr
    assert secret_val not in str(settings)
    assert secret_val not in repr(settings)
    assert secret_val not in repr(settings.gemini_api_key)
    assert settings.gemini_api_key.get_secret_value() == secret_val


def test_config_invalid_mode():
    with pytest.raises(ValidationError):
        Settings(LLM_MODE="unsupported_mode")


def test_config_bound_violations():
    with pytest.raises(ValidationError):
        Settings(COST_BUDGET_USD=-1.0)

    with pytest.raises(ValidationError):
        Settings(SERVICE_LEVEL=1.5)
