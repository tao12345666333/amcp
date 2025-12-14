from amcp.agent_spec import get_default_agent_spec


def test_agent_spec_default():
    spec = get_default_agent_spec()
    assert spec.name == "default"
    assert len(spec.system_prompt) > 0
