"""Tests for interactive initialization configuration choices."""

from amcp.init_wizard import _resolve_api_type


def test_resolve_api_type_uses_supported_any_llm_provider():
    assert _resolve_api_type("gmi", is_custom=False) == "gmi"


def test_resolve_api_type_keeps_custom_provider_openai_compatible():
    assert _resolve_api_type("custom", is_custom=True) == "openai"
