# AMCP Plugins

This directory contains official AMCP plugins that extend functionality through custom commands, agents, skills, hooks, and workflows.

## What are AMCP Plugins?

AMCP plugins are extensions that enhance AMCP with:
- **Custom slash commands** - Shortcuts for common tasks
- **Specialized agents** - Pre-configured agents for specific domains
- **Skills** - Knowledge and behavior patterns for agents
- **Hooks** - Event-driven automation and validation
- **Workflows** - Multi-step structured processes

Plugins can be shared across projects and teams, providing consistent tooling and workflows.

## Plugins in This Directory

| Name | Description | Contents |
|------|-------------|----------|
| [code-review](./code-review/) | Multi-agent code review with confidence scoring | **Command:** `/code-review` - Automated code review workflow<br>**Agents:** `code-reviewer`, `security-checker`, `style-checker` |
| [feature-dev](./feature-dev/) | 7-phase structured feature development | **Command:** `/feature-dev` - Guided development workflow<br>**Agents:** `code-explorer`, `code-architect`, `code-reviewer` |
| [security-guidance](./security-guidance/) | Security validation and warnings | **Hook:** PreToolUse - Monitors dangerous patterns<br>**Skill:** Security best practices |

## Installation

1. **Copy plugin to your project:**
   ```bash
   cp -r examples/plugins/feature-dev .amcp/plugins/
   ```

2. **Or copy to user-level config:**
   ```bash
   cp -r examples/plugins/feature-dev ~/.config/amcp/plugins/
   ```

3. **Use the plugin commands:**
   ```bash
   amcp
   AMCP> /feature-dev Add user authentication
   ```

## Plugin Structure

Each plugin follows this standard structure:

```
plugin-name/
├── plugin.json           # Plugin metadata and configuration
├── commands/             # Slash commands (optional)
│   └── command-name.md   # Command definition
├── agents/               # Specialized agents (optional)
│   └── agent-name.yaml   # Agent specification
├── skills/               # Agent skills (optional)
│   └── skill-name/
│       └── SKILL.md      # Skill definition
├── hooks/                # Event handlers (optional)
│   └── hook-name.md      # Hook configuration (simplified format)
└── README.md             # Plugin documentation
```

## Creating Your Own Plugin

### 1. Create plugin directory

```bash
mkdir -p .amcp/plugins/my-plugin/{commands,agents,skills,hooks}
```

### 2. Add plugin.json

```json
{
  "name": "my-plugin",
  "version": "1.0.0",
  "description": "My custom AMCP plugin",
  "author": "Your Name",
  "components": {
    "commands": ["commands/*.md"],
    "agents": ["agents/*.yaml"],
    "skills": ["skills/*/SKILL.md"],
    "hooks": ["hooks/*.md"]
  }
}
```

### 3. Add components

Create commands, agents, skills, or hooks as needed.

### 4. Test your plugin

```bash
amcp --plugin .amcp/plugins/my-plugin
```

## Plugin Configuration

Plugins can be configured in your project's `.amcp/settings.json`:

```json
{
  "plugins": {
    "enabled": ["feature-dev", "code-review"],
    "disabled": ["security-guidance"],
    "paths": [
      ".amcp/plugins",
      "~/.config/amcp/plugins"
    ]
  }
}
```

## Contributing

When creating plugins:

1. Follow the standard plugin structure
2. Include a comprehensive README.md
3. Add plugin metadata in `plugin.json`
4. Document all commands and agents
5. Provide usage examples
6. Test thoroughly before sharing

## Learn More

- [AMCP Documentation](../../README.md)
- [Commands Guide](../../docs/commands.md)
- [Agents Guide](../../docs/agents.md)
- [Skills Guide](../../docs/skills.md)
- [Hooks Guide](../../docs/hooks.md)
