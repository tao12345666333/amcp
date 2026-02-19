import amcp.config as config_module


def test_config_dir_default():
    assert config_module.CONFIG_DIR.name == "amcp"
    assert "config" in str(config_module.CONFIG_DIR).lower()


def test_load_config():
    config = config_module.load_config()
    assert isinstance(config, config_module.AMCPConfig)
    assert isinstance(config.servers, dict)
    assert config.context is None or isinstance(config.context, config_module.ContextConfig)


def test_decode_encode_context_roundtrip():
    raw = {
        "progressive_tools": True,
        "progressive_skills": False,
        "response_ratio": 0.25,
        "min_prompt_budget": 1500,
        "base_prompt_max_tokens": 1200,
        "tool_budget_ratio": 0.5,
        "skill_budget_ratio": 0.2,
        "memory_budget_ratio": 0.2,
        "rules_budget_ratio": 0.1,
        "tool_relevance_threshold": 0.2,
        "skill_relevance_threshold": 0.3,
        "tool_tiers": {"task": "hidden"},
    }

    cfg = config_module._decode_context(raw)
    assert cfg is not None
    assert cfg.progressive_skills is False
    assert cfg.tool_tiers["task"] == "hidden"

    encoded = config_module._encode_context(cfg)
    assert encoded is not None
    assert encoded["min_prompt_budget"] == 1500
    assert encoded["tool_tiers"]["task"] == "hidden"


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
