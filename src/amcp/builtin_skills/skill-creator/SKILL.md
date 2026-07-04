---
name: skill-creator
description: Create or update AMCP skills. Use when designing, structuring, or packaging skills with scripts, references, and assets. This skill should be used when users want to create a new skill (or update an existing skill) that extends AMCP's capabilities with specialized knowledge, workflows, or tool integrations.
---

# Skill Creator

This skill provides guidance for creating effective AMCP skills.

## About Skills

Skills are modular, self-contained packages that extend the agent's capabilities by providing
specialized knowledge, workflows, and tools. Think of them as "onboarding guides" for specific
domains or tasks — they transform the agent from a general-purpose agent into a specialized agent
equipped with procedural knowledge that no model can fully possess.

### Skill Location Policy

When creating a skill, place it in one of these roots:

1. Project-local: `$workspace/.amcp/skills/<skill-name>`
2. Home agent-level: `~/.agents/skills/<skill-name>` (shared across agent tools)
3. User-level: `~/.config/amcp/skills/<skill-name>` (shared across AMCP workspaces)

Prefer project-local by default. Use home agent-level or user-level only when the user explicitly wants the skill available across multiple workspaces.

### What Skills Provide

1. Specialized workflows - Multi-step procedures for specific domains
2. Tool integrations - Instructions for working with specific file formats or APIs
3. Domain expertise - Company-specific knowledge, schemas, business logic
4. Bundled resources - Scripts, references, and assets for complex and repetitive tasks

## Core Principles

### Concise is Key

The context window is a public good. Skills share the context window with everything else the agent needs: system prompt, conversation history, other skills' metadata, and the actual user request.

**Default assumption: the agent is already very smart.** Only add context the agent doesn't already have. Challenge each piece of information: "Does the agent really need this explanation?" and "Does this paragraph justify its token cost?"

Prefer concise examples over verbose explanations.

### Set Appropriate Degrees of Freedom

Match the level of specificity to the task's fragility and variability:

**High freedom (text-based instructions)**: Use when multiple approaches are valid, decisions depend on context, or heuristics guide the approach.

**Medium freedom (pseudocode or scripts with parameters)**: Use when a preferred pattern exists, some variation is acceptable, or configuration affects behavior.

**Low freedom (specific scripts, few parameters)**: Use when operations are fragile and error-prone, consistency is critical, or a specific sequence must be followed.

### Anatomy of a Skill

Every skill consists of a required SKILL.md file and optional bundled resources:

```
skill-name/
├── SKILL.md (required)
│   ├── YAML frontmatter metadata (required)
│   │   ├── name: (required)
│   │   └── description: (required)
│   └── Markdown instructions (required)
└── Bundled Resources (optional)
    ├── scripts/          - Executable code (Python/Bash/etc.)
    ├── references/       - Documentation intended to be loaded into context as needed
    └── assets/           - Files used in output (templates, icons, fonts, etc.)
```

#### SKILL.md (required)

Every SKILL.md consists of:

- **Frontmatter** (YAML): Contains `name` and `description` fields. These are the only fields that the agent reads to determine when the skill gets used, thus it is very important to be clear and comprehensive in describing what the skill is, and when it should be used.
- **Body** (Markdown): Instructions and guidance for using the skill. Only loaded AFTER the skill triggers (if at all).

#### Bundled Resources (optional)

##### Scripts (`scripts/`)

Executable code (Python/Bash/etc.) for tasks that require deterministic reliability or are repeatedly rewritten.

- **When to include**: When the same code is being rewritten repeatedly or deterministic reliability is needed
- **Benefits**: Token efficient, deterministic, may be executed without loading into context
- **Note**: Scripts may still need to be read by the agent for patching or environment-specific adjustments

##### References (`references/`)

Documentation and reference material intended to be loaded as needed into context.

- **When to include**: For documentation that the agent should reference while working
- **Use cases**: Database schemas, API documentation, domain knowledge, company policies
- **Benefits**: Keeps SKILL.md lean, loaded only when the agent determines it's needed
- **Best practice**: If files are large (>10k words), include grep search patterns in SKILL.md

##### Assets (`assets/`)

Files not intended to be loaded into context, but rather used within the output the agent produces.

- **When to include**: When the skill needs files that will be used in the final output
- **Use cases**: Templates, images, icons, boilerplate code, fonts, sample documents
- **Benefits**: Separates output resources from documentation

#### What to NOT Include in a Skill

A skill should only contain essential files. Do NOT create:

- README.md, INSTALLATION_GUIDE.md, QUICK_REFERENCE.md, CHANGELOG.md, etc.
- The skill should only contain information needed for an AI agent to do the job.

### Progressive Disclosure Design Principle

Skills use a three-level loading system to manage context efficiently:

1. **Metadata (name + description)** - Always in context (~100 words)
2. **SKILL.md body** - When skill triggers (<5k words)
3. **Bundled resources** - As needed by the agent (unlimited)

Keep SKILL.md body to the essentials and under 500 lines to minimize context bloat. Split content into separate files when approaching this limit.

## Skill Creation Process

Skill creation involves these steps:

1. Understand the skill with concrete examples
2. Plan reusable skill contents (scripts, references, assets)
3. Initialize the skill (run `init_skill.py`)
4. Edit the skill (implement resources and write SKILL.md)
5. Validate the skill (run `validate_skill.py`)
6. Iterate based on real usage

Follow these steps in order, skipping only if there is a clear reason why they are not applicable.

### Skill Naming

- Use lowercase letters, digits, and hyphens only; normalize user-provided titles to hyphen-case (e.g., "Plan Mode" -> `plan-mode`).
- Generate names under 64 characters (letters, digits, hyphens).
- Prefer short, verb-led phrases that describe the action.
- Namespace by tool when it improves clarity (e.g., `gh-address-comments`, `docker-deploy`).
- Name the skill folder exactly after the skill name.

### Step 1: Understanding the Skill with Concrete Examples

To create an effective skill, clearly understand concrete examples of how the skill will be used. Ask questions like:

- "What functionality should the skill support?"
- "Can you give some examples of how this skill would be used?"
- "What would a user say that should trigger this skill?"

Conclude this step when there is a clear sense of the functionality the skill should support.

### Step 2: Planning the Reusable Skill Contents

Analyze each concrete example by:

1. Considering how to execute on the example from scratch
2. Identifying what scripts, references, and assets would be helpful

### Step 3: Initializing the Skill

When creating a new skill from scratch, run the `init_skill.py` script bundled with this skill:

```bash
python <path-to-skill-creator>/scripts/init_skill.py <skill-name> --path <output-directory> [--resources scripts,references,assets]
```

Examples:

```bash
# Project-local skill
python <path>/scripts/init_skill.py my-skill --path .amcp/skills

# User-level skill
python <path>/scripts/init_skill.py my-skill --path ~/.config/amcp/skills

# Home agent-level skill
python <path>/scripts/init_skill.py my-skill --path ~/.agents/skills

# With specific resources
python <path>/scripts/init_skill.py my-skill --path .amcp/skills --resources scripts,references
```

The script creates the skill directory with a SKILL.md template and optional resource directories.

### Step 4: Edit the Skill

When editing the skill, remember it is being created for another instance of the agent to use. Include information that would be beneficial and non-obvious. Consider what procedural knowledge, domain-specific details, or reusable assets would help.

#### Frontmatter

Write the YAML frontmatter with these fields:

- `name` (required): The skill name
- `description` (required): This is the primary triggering mechanism. Include both what the skill does and specific triggers/contexts for when to use it. Include all "when to use" information here, not in the body.
- `auto_trigger` (optional, default: `true`): Whether the agent can automatically use this skill when relevant. Set to `false` for skills that should only be invoked explicitly via `/skill:<name>`.
- `parameters` (optional): List of parameters that can be passed when invoking the skill explicitly.

Example frontmatter with all fields:

```yaml
---
name: deploy
description: Deploy the application to a specified environment. Use when the user wants to deploy code.
auto_trigger: false
parameters:
  - name: env
    description: Target environment
    required: true
    enum: [staging, production]
  - name: version
    description: Version to deploy
    required: false
    default: latest
---
```

#### Body

Write clear, concise instructions for using the skill and its bundled resources. Use imperative/infinitive form.

### Step 5: Validate the Skill

Once development is complete, validate the skill:

```bash
python <path-to-skill-creator>/scripts/validate_skill.py <path/to/skill-folder>
```

The validation script checks YAML frontmatter format, required fields, naming rules, and file organization. Fix any reported issues and run again.

### Step 6: Iterate

After testing the skill, iterate based on real usage:

1. Use the skill on real tasks
2. Notice struggles or inefficiencies
3. Identify how SKILL.md or bundled resources should be updated
4. Implement changes and test again
