from amcp.config import CONFIG_DIR, AMCPConfig, load_config


def test_config_dir_default():
    assert CONFIG_DIR.name == "amcp"
    assert "config" in str(CONFIG_DIR).lower()


def test_load_config():
    config = load_config()
    assert isinstance(config, AMCPConfig)
    assert isinstance(config.servers, dict)
