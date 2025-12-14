import pytest


@pytest.fixture
def temp_workspace(tmp_path):
    """Create a temporary workspace directory."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


@pytest.fixture
def sample_config(tmp_path):
    """Create a sample config file."""
    config_file = tmp_path / "config.toml"
    config_file.write_text("""
[chat]
base_url = "https://api.example.com/v1"
model = "test-model"
api_key = "test-key"

[servers.test]
url = "https://test.mcp.server"
""")
    return config_file
