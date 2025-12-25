"""Tests for the models database module."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from amcp.models_db import (
    BUILTIN_MODELS,
    DEFAULT_CONTEXT_WINDOW,
    ModelInfo,
    ModelsDatabase,
    ProviderInfo,
    get_context_window_from_database,
    load_models_cache,
    save_models_cache,
)


class TestModelInfo:
    """Tests for ModelInfo dataclass."""

    def test_default_values(self):
        """Test default values."""
        model = ModelInfo(id="test-model", name="Test Model")
        assert model.id == "test-model"
        assert model.name == "Test Model"
        assert model.context_window == DEFAULT_CONTEXT_WINDOW
        assert model.tool_call is False

    def test_from_api_data(self):
        """Test creating from API data."""
        api_data = {
            "name": "GPT-4 Turbo",
            "family": "GPT-4",
            "limit": {"context": 128000, "output": 4096},
            "tool_call": True,
            "reasoning": False,
            "cost": {"input": 10.0, "output": 30.0},
        }
        model = ModelInfo.from_api_data("gpt-4-turbo", api_data, "openai")

        assert model.id == "gpt-4-turbo"
        assert model.name == "GPT-4 Turbo"
        assert model.context_window == 128000
        assert model.output_limit == 4096
        assert model.tool_call is True
        assert model.provider_id == "openai"


class TestProviderInfo:
    """Tests for ProviderInfo dataclass."""

    def test_default_values(self):
        """Test default values."""
        provider = ProviderInfo(id="test", name="Test Provider")
        assert provider.id == "test"
        assert provider.name == "Test Provider"
        assert provider.models == {}

    def test_from_api_data(self):
        """Test creating from API data."""
        api_data = {
            "name": "OpenAI",
            "api": "https://api.openai.com/v1",
            "env": ["OPENAI_API_KEY"],
            "models": {
                "gpt-4o": {
                    "name": "GPT-4o",
                    "limit": {"context": 128000},
                }
            },
        }
        provider = ProviderInfo.from_api_data("openai", api_data)

        assert provider.id == "openai"
        assert provider.name == "OpenAI"
        assert provider.api_url == "https://api.openai.com/v1"
        assert "OPENAI_API_KEY" in provider.env_vars
        assert "gpt-4o" in provider.models


class TestModelsDatabase:
    """Tests for ModelsDatabase class."""

    def test_empty_database(self):
        """Test empty database."""
        db = ModelsDatabase()
        assert db.providers == {}
        assert db.list_providers() == []

    def test_get_provider(self):
        """Test getting a provider."""
        provider = ProviderInfo(id="test", name="Test")
        db = ModelsDatabase(providers={"test": provider})

        assert db.get_provider("test") == provider
        assert db.get_provider("nonexistent") is None

    def test_get_model(self):
        """Test getting a model."""
        model = ModelInfo(id="test-model", name="Test Model")
        provider = ProviderInfo(id="test", name="Test", models={"test-model": model})
        db = ModelsDatabase(providers={"test": provider})

        assert db.get_model("test", "test-model") == model
        assert db.get_model("test", "nonexistent") is None
        assert db.get_model("nonexistent", "test-model") is None

    def test_find_model_by_name(self):
        """Test finding a model by name."""
        model = ModelInfo(id="gpt-4o", name="GPT-4o")
        provider = ProviderInfo(id="openai", name="OpenAI", models={"gpt-4o": model})
        db = ModelsDatabase(providers={"openai": provider})

        found_model, found_provider = db.find_model_by_name("gpt-4o")
        assert found_model == model
        assert found_provider == provider

        # Test partial matching
        found_model, found_provider = db.find_model_by_name("gpt-4")
        assert found_model == model

    def test_to_dict_and_from_dict(self):
        """Test serialization round-trip."""
        model = ModelInfo(id="test-model", name="Test", context_window=100000)
        provider = ProviderInfo(id="test", name="Test Provider", models={"test-model": model})
        db = ModelsDatabase(providers={"test": provider}, fetched_at="2024-01-01T00:00:00")

        data = db.to_dict()
        restored = ModelsDatabase.from_dict(data)

        assert restored.fetched_at == "2024-01-01T00:00:00"
        assert "test" in restored.providers
        assert "test-model" in restored.providers["test"].models
        assert restored.providers["test"].models["test-model"].context_window == 100000


class TestBuiltinModels:
    """Tests for built-in model fallbacks."""

    def test_builtin_models_exist(self):
        """Test that built-in models are defined."""
        assert "gpt-4o" in BUILTIN_MODELS
        assert "claude-3.5-sonnet" in BUILTIN_MODELS
        assert "deepseek-chat" in BUILTIN_MODELS

    def test_builtin_values_reasonable(self):
        """Test that built-in values are reasonable."""
        for model, ctx in BUILTIN_MODELS.items():
            assert ctx >= 8_000, f"{model} context too small"
            assert ctx <= 2_000_000, f"{model} context too large"


class TestGetContextWindowFromDatabase:
    """Tests for get_context_window_from_database function."""

    def test_returns_builtin_when_no_cache(self):
        """Test fallback to built-in values."""
        with patch("amcp.models_db.load_models_cache", return_value=None):
            result = get_context_window_from_database("gpt-4o")
            assert result == BUILTIN_MODELS["gpt-4o"]

    def test_returns_default_for_unknown(self):
        """Test default for unknown models."""
        with patch("amcp.models_db.load_models_cache", return_value=None):
            result = get_context_window_from_database("unknown-model-xyz")
            assert result == DEFAULT_CONTEXT_WINDOW

    def test_uses_database_when_available(self):
        """Test using database values."""
        model = ModelInfo(id="custom-model", name="Custom", context_window=999999)
        provider = ProviderInfo(id="custom", name="Custom", models={"custom-model": model})
        db = ModelsDatabase(providers={"custom": provider})

        with patch("amcp.models_db.load_models_cache", return_value=db):
            result = get_context_window_from_database("custom-model")
            assert result == 999999


class TestCacheFunctions:
    """Tests for cache save/load functions."""

    def test_save_and_load_cache(self):
        """Test saving and loading cache."""
        model = ModelInfo(id="test", name="Test", context_window=50000)
        provider = ProviderInfo(id="provider", name="Provider", models={"test": model})
        db = ModelsDatabase(providers={"provider": provider}, fetched_at="2024-01-01")

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = Path(tmpdir) / "models.json"

            with patch("amcp.models_db.MODELS_CACHE_FILE", cache_file):
                with patch("amcp.models_db.CACHE_DIR", Path(tmpdir)):
                    # Save
                    save_models_cache(db)

                    # Verify file exists
                    assert cache_file.exists()

                    # Load
                    loaded = load_models_cache()
                    assert loaded is not None
                    assert loaded.fetched_at == "2024-01-01"
                    assert "provider" in loaded.providers

    def test_load_returns_none_when_no_cache(self):
        """Test load returns None when no cache file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = Path(tmpdir) / "nonexistent.json"

            with patch("amcp.models_db.MODELS_CACHE_FILE", cache_file):
                result = load_models_cache()
                assert result is None
