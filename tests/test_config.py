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


def test_decode_encode_chat_tool_limits_roundtrip():
    raw = {
        "tool_loop_limit": 300,
        "bash_tool_limit": 100,
        "default_max_lines": 400,
    }

    cfg = config_module._decode_chat(raw)
    assert cfg is not None
    assert cfg.tool_loop_limit == 300
    assert cfg.bash_tool_limit == 100

    encoded = config_module._encode_chat(cfg)
    assert encoded is not None
    assert encoded["tool_loop_limit"] == 300
    assert encoded["bash_tool_limit"] == 100


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


def test_decode_encode_telegram_roundtrip_with_policies():
    raw = {
        "enabled": True,
        "bot_token": "token",
        "allowed_users": [1],
        "admin_users": [1],
        "dm_policy": "pairing",
        "group_policy": "mention",
        "group_allow_users": [2, 3],
        "typing_indicator": True,
        "typing_interval_seconds": 5,
        "max_queue_size": 25,
        "pairing": {
            "enabled": True,
            "code_ttl_seconds": 900,
            "max_pending": 50,
        },
        "groups": {
            "-100123": {
                "enabled": True,
                "group_policy": "allowlist",
                "require_mention": True,
                "allow_users": [4],
                "topics": {
                    "42": {
                        "enabled": True,
                        "group_policy": "open",
                        "require_mention": False,
                        "allow_users": [5],
                    }
                },
            }
        },
    }

    cfg = config_module._decode_telegram(raw)
    assert cfg is not None
    assert cfg.dm_policy == "pairing"
    assert cfg.group_policy == "mention"
    assert cfg.group_allow_users == [2, 3]
    assert cfg.typing_interval_seconds == 5
    assert cfg.max_queue_size == 25
    assert cfg.pairing.code_ttl_seconds == 900
    assert cfg.groups["-100123"].topics["42"].group_policy == "open"

    encoded = config_module._encode_telegram(cfg)
    assert encoded is not None
    assert encoded["dm_policy"] == "pairing"
    assert encoded["group_policy"] == "mention"
    assert encoded["pairing"]["max_pending"] == 50
    assert encoded["groups"]["-100123"]["topics"]["42"]["group_policy"] == "open"


def test_decode_telegram_invalid_policy_falls_back_to_defaults():
    cfg = config_module._decode_telegram(
        {
            "dm_policy": "invalid",
            "group_policy": "invalid",
            "typing_interval_seconds": 0,
            "max_queue_size": 0,
        }
    )

    assert cfg is not None
    assert cfg.dm_policy == "allowlist"
    assert cfg.group_policy == "mention"
    assert cfg.typing_interval_seconds == 1
    assert cfg.max_queue_size == 1
