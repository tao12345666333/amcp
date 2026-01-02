---
description: How to create and use custom skills and slash commands
---

# Creating Skills and Slash Commands

This workflow explains how to create custom skills and slash commands for AMCP.

## Creating a Skill

1. Create a skill directory:
   ```bash
   mkdir -p ~/.config/amcp/skills/my-skill
   ```

2. Create a SKILL.md file with YAML frontmatter:
   ```bash
   cat > ~/.config/amcp/skills/my-skill/SKILL.md << 'EOF'
   ---
   name: my-skill
   description: My custom skill description
   ---
   
   # Skill Content
   
   Your skill instructions go here.
   EOF
   ```

3. In AMCP CLI, activate the skill:
   ```
   /skills activate my-skill
   ```

## Creating a Slash Command

1. Create a command file:
   ```bash
   mkdir -p ~/.config/amcp/commands
   cat > ~/.config/amcp/commands/mycommand.toml << 'EOF'
   description = "My custom command"
   prompt = "Your prompt template here with {{args}} placeholder"
   EOF
   ```

2. Use it in AMCP CLI:
   ```
   /mycommand your arguments here
   ```

## Available Built-in Commands

- `/help` - Show all available commands
- `/skills list` - List available skills
- `/skills activate <name>` - Activate a skill
- `/skills deactivate <name>` - Deactivate a skill
- `/skills show <name>` - Show skill content
- `/clear` - Clear conversation history
- `/info` - Show session info
- `/exit` - Exit the chat
