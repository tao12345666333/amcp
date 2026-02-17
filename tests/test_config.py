import amcp.config as config_module


def test_config_dir_default():
    assert config_module.CONFIG_DIR.name == "amcp"
    assert "config" in str(config_module.CONFIG_DIR).lower()


def test_load_config():
    config = config_module.load_config()
    assert isinstance(config, config_module.AMCPConfig)
    assert isinstance(config.servers, dict)


def test_decode_encode_automation_roundtrip():
    raw = {
        "enabled": True,
        "default_timeout": 180,
        "jobs": [
            {
                "name": "ci-check",
                "command": "Check CI status",
                "skill": "ci-checker",
                "enabled": True,
                "notify": True,
                "timeout": 90,
                "tags": ["ci"],
                "schedule": "*/15 * * * *",
            }
        ],
    }

    cfg = config_module._decode_automation(raw)
    assert cfg is not None
    assert cfg.enabled is True
    assert cfg.default_timeout == 180
    assert len(cfg.jobs) == 1
    assert cfg.jobs[0].name == "ci-check"
    assert cfg.jobs[0].timeout == 90

    encoded = config_module._encode_automation(cfg)
    assert encoded is not None
    assert encoded["default_timeout"] == 180
    assert encoded["jobs"][0]["name"] == "ci-check"


def test_decode_automation_uses_default_timeout():
    cfg = config_module._decode_automation(
        {
            "default_timeout": 222,
            "jobs": [
                {
                    "name": "job-a",
                    "command": "run it",
                }
            ],
        }
    )
    assert cfg is not None
    assert len(cfg.jobs) == 1
    assert cfg.jobs[0].timeout == 222


def test_decode_encode_automation_none():
    assert config_module._decode_automation(None) is None
    assert config_module._encode_automation(None) is None
