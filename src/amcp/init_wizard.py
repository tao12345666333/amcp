"""Interactive initialization wizard for AMCP configuration."""

from __future__ import annotations

import logging
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from .config import (
    CONFIG_DIR,
    CONFIG_FILE,
    AMCPConfig,
    ChatConfig,
    ModelConfig,
    Server,
    save_config,
)
from .models_db import (
    ModelsDatabase,
    fetch_models_from_api,
    save_models_cache,
)

logger = logging.getLogger(__name__)
console = Console()


def prompt_yes_no(question: str, default: bool = True) -> bool:
    """Prompt user for yes/no answer."""
    default_str = "[Y/n]" if default else "[y/N]"
    while True:
        response = console.input(f"{question} {default_str}: ").strip().lower()
        if not response:
            return default
        if response in ("y", "yes"):
            return True
        if response in ("n", "no"):
            return False
        console.print("[yellow]Please enter 'y' for yes or 'n' for no[/yellow]")


def prompt_choice(
    question: str,
    choices: list[str],
    default: str | None = None,
    show_numbers: bool = True,
) -> str:
    """Prompt user to select from a list of choices."""
    if show_numbers:
        console.print(f"\n{question}")
        for i, choice in enumerate(choices, 1):
            marker = " *" if choice == default else ""
            console.print(f"  [{i}] {choice}{marker}")

        while True:
            prompt = "Enter number"
            if default:
                prompt += f" (default: {choices.index(default) + 1})"
            response = console.input(f"{prompt}: ").strip()

            if not response and default:
                return default

            try:
                idx = int(response) - 1
                if 0 <= idx < len(choices):
                    return choices[idx]
            except ValueError:
                pass

            console.print(f"[yellow]Please enter a number between 1 and {len(choices)}[/yellow]")
    else:
        # Free text with autocomplete hint
        console.print(f"\n{question}")
        console.print(f"[dim]Options: {', '.join(choices[:10])}{'...' if len(choices) > 10 else ''}[/dim]")
        while True:
            prompt = "Enter choice"
            if default:
                prompt += f" (default: {default})"
            response = console.input(f"{prompt}: ").strip()

            if not response and default:
                return default

            if response in choices:
                return response

            # Try partial match
            matches = [c for c in choices if response.lower() in c.lower()]
            if len(matches) == 1:
                return matches[0]
            elif matches:
                console.print(f"[yellow]Multiple matches: {', '.join(matches[:5])}[/yellow]")
            else:
                console.print(f"[yellow]'{response}' not found in options[/yellow]")


def prompt_string(question: str, default: str | None = None, allow_empty: bool = False) -> str:
    """Prompt user for string input."""
    prompt = question
    if default:
        prompt += f" (default: {default})"
    prompt += ": "

    while True:
        response = console.input(prompt).strip()
        if not response:
            if default:
                return default
            if allow_empty:
                return ""
            console.print("[yellow]This field is required[/yellow]")
            continue
        return response


def prompt_api_key(provider_name: str, env_vars: list[str]) -> str:
    """Prompt user for API key with hints about environment variables."""
    console.print(f"\n[bold]API Key for {provider_name}[/bold]")
    if env_vars:
        console.print(f"[dim]Environment variables checked: {', '.join(env_vars)}[/dim]")

    # Check if any env var is already set
    import os

    for env_var in env_vars:
        if os.environ.get(env_var):
            use_env = prompt_yes_no(f"Found {env_var} in environment. Use it?", default=True)
            if use_env:
                return ""  # Will use env var

    console.print("[dim]Leave empty to use environment variable later[/dim]")
    return console.input("API Key: ").strip()


def download_models_database() -> ModelsDatabase | None:
    """Download models database from models.dev with progress indicator."""
    console.print("\n[bold]Downloading model database from models.dev...[/bold]")

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task("Fetching models data...", total=None)
            db = fetch_models_from_api(timeout=60.0)

        # Save to cache
        cache_path = save_models_cache(db)

        # Show summary
        total_models = sum(len(p.models) for p in db.providers.values())
        console.print(f"[green]✓ Downloaded {len(db.providers)} providers with {total_models} models[/green]")
        console.print(f"[dim]Cached to: {cache_path}[/dim]")

        return db

    except Exception as e:
        console.print(f"[red]Failed to download models data: {e}[/red]")
        return None


def select_provider(db: ModelsDatabase) -> tuple[str, str, list[str]] | None:
    """Let user select a provider from the database.

    Returns (provider_id, api_url, env_vars) or None for custom.
    """
    # Get popular providers first
    popular = ["openai", "anthropic", "google", "deepseek", "mistral", "xai", "groq", "alibaba", "cohere"]
    all_providers = db.list_providers()

    # Sort: popular first, then alphabetical
    sorted_providers = []
    for p in popular:
        if p in all_providers:
            sorted_providers.append(p)
    for p in sorted(all_providers):
        if p not in sorted_providers:
            sorted_providers.append(p)

    # Add custom option
    sorted_providers.append("__custom__")

    # Show provider selection
    console.print("\n[bold]Select a model provider:[/bold]")

    # Show table for popular providers
    table = Table(show_header=True, header_style="bold")
    table.add_column("#", style="dim")
    table.add_column("Provider ID")
    table.add_column("Name")
    table.add_column("Models")

    for i, pid in enumerate(sorted_providers[:15], 1):
        if pid == "__custom__":
            table.add_row(str(i), "[cyan]custom[/cyan]", "Enter custom provider", "-")
        else:
            provider = db.get_provider(pid)
            if provider:
                table.add_row(str(i), pid, provider.name, str(len(provider.models)))

    if len(sorted_providers) > 15:
        table.add_row("...", f"({len(sorted_providers) - 15} more)", "", "")

    console.print(table)

    while True:
        response = console.input("\nEnter number or provider ID: ").strip()

        try:
            idx = int(response) - 1
            if 0 <= idx < len(sorted_providers):
                selected = sorted_providers[idx]
                if selected == "__custom__":
                    return None
                provider = db.get_provider(selected)
                if provider:
                    return (provider.id, provider.api_url, provider.env_vars)
        except ValueError:
            # Try direct ID match
            if response.lower() == "custom":
                return None
            if response in all_providers:
                provider = db.get_provider(response)
                if provider:
                    return (provider.id, provider.api_url, provider.env_vars)

        console.print("[yellow]Invalid selection. Please try again.[/yellow]")


def select_model(db: ModelsDatabase, provider_id: str) -> tuple[str, int, int] | None:
    """Let user select a model from a provider.

    Returns (model_id, context_window, output_limit) or None.
    """
    provider = db.get_provider(provider_id)
    if not provider:
        return None

    models = list(provider.models.values())
    if not models:
        console.print(f"[yellow]No models found for {provider_id}[/yellow]")
        return None

    # Sort by name
    models.sort(key=lambda m: m.name)

    console.print(f"\n[bold]Select a model from {provider.name}:[/bold]")

    # Show table
    table = Table(show_header=True, header_style="bold")
    table.add_column("#", style="dim")
    table.add_column("Model ID")
    table.add_column("Name")
    table.add_column("Context")
    table.add_column("Features")

    for i, model in enumerate(models[:20], 1):
        features = []
        if model.tool_call:
            features.append("🔧")
        if model.reasoning:
            features.append("🧠")
        if model.attachment:
            features.append("📎")

        ctx = f"{model.context_window:,}"
        table.add_row(str(i), model.id, model.name, ctx, " ".join(features))

    if len(models) > 20:
        table.add_row("...", f"({len(models) - 20} more)", "", "", "")

    console.print(table)
    console.print("[dim]🔧=Tool Call  🧠=Reasoning  📎=Attachments[/dim]")

    while True:
        response = console.input("\nEnter number or model ID: ").strip()

        try:
            idx = int(response) - 1
            if 0 <= idx < len(models):
                model = models[idx]
                return (model.id, model.context_window, model.output_limit)
        except ValueError:
            # Try direct ID match
            for model in models:
                if model.id == response or model.id.lower() == response.lower():
                    return (model.id, model.context_window, model.output_limit)

        console.print("[yellow]Invalid selection. Please try again.[/yellow]")


def configure_custom_provider() -> tuple[str, str, str, int]:
    """Configure a custom provider not in the database.

    Returns (provider_name, base_url, model_name, context_window).
    """
    console.print("\n[bold]Configure Custom Provider[/bold]")
    console.print("[dim]Since this provider is not in our database, you'll need to provide the details manually.[/dim]")

    provider_name = prompt_string("Provider name (e.g., 'my-provider')")
    base_url = prompt_string("API base URL (e.g., 'https://api.example.com/v1')")
    model_name = prompt_string("Model name/ID")

    # Context window with default
    console.print("\n[dim]If you don't know the context window size, 32,000 is a safe default.[/dim]")
    while True:
        ctx_str = prompt_string("Context window size", default="32000")
        try:
            context_window = int(ctx_str.replace(",", "").replace("_", ""))
            break
        except ValueError:
            console.print("[yellow]Please enter a valid number[/yellow]")

    return (provider_name, base_url, model_name, context_window)


def run_init_wizard() -> Path:
    """Run the interactive initialization wizard.

    Returns path to the created config file.
    """
    console.print(
        Panel.fit(
            "[bold blue]AMCP Configuration Wizard[/bold blue]\n\n"
            "This wizard will help you set up AMCP with your preferred AI model provider.",
            title="Welcome",
        )
    )

    # Check if config already exists
    if CONFIG_FILE.exists():
        overwrite = prompt_yes_no(
            f"\nConfig file already exists at {CONFIG_FILE}. Overwrite?",
            default=False,
        )
        if not overwrite:
            console.print("[yellow]Keeping existing configuration.[/yellow]")
            return CONFIG_FILE

    # Step 1: Download models database?
    console.print("\n[bold]Step 1: Model Database[/bold]")
    console.print("AMCP can download a database of AI models from models.dev")
    console.print("This provides accurate context window sizes and other model parameters.")

    use_models_db = prompt_yes_no("Download model database from models.dev?", default=True)

    db: ModelsDatabase | None = None
    provider_id: str | None = None
    model_id: str | None = None
    base_url: str | None = None
    api_key: str = ""
    context_window: int | None = None
    output_limit: int | None = None
    is_custom = False

    if use_models_db:
        db = download_models_database()

    if db:
        # Step 2: Select provider
        console.print("\n[bold]Step 2: Select Provider[/bold]")
        provider_result = select_provider(db)

        if provider_result:
            provider_id, base_url, env_vars = provider_result

            # Step 3: Select model
            console.print("\n[bold]Step 3: Select Model[/bold]")
            model_result = select_model(db, provider_id)

            if model_result:
                model_id, context_window, output_limit = model_result

            # Step 4: API Key
            console.print("\n[bold]Step 4: API Key[/bold]")
            api_key = prompt_api_key(provider_id, env_vars)
        else:
            # Custom provider
            is_custom = True
            custom_result = configure_custom_provider()
            provider_id = custom_result[0]
            base_url = custom_result[1]
            model_id = custom_result[2]
            context_window = custom_result[3]

            console.print("\n[bold]Step 4: API Key[/bold]")
            api_key = prompt_api_key(provider_id, [])
    else:
        # No database, configure manually
        is_custom = True
        console.print("\n[bold]Step 2: Configure Provider Manually[/bold]")
        custom_result = configure_custom_provider()
        provider_id = custom_result[0]
        base_url = custom_result[1]
        model_id = custom_result[2]
        context_window = custom_result[3]

        console.print("\n[bold]Step 3: API Key[/bold]")
        api_key = prompt_api_key(provider_id, [])

    # Build configuration
    model_config = ModelConfig(
        provider_id=provider_id,
        model_id=model_id,
        context_window=context_window,
        output_limit=output_limit,
        is_custom=is_custom,
    )

    chat_config = ChatConfig(
        base_url=base_url,
        model=model_id,
        api_key=api_key if api_key else None,
        model_config=model_config,
        tool_loop_limit=300,
        default_max_lines=400,
        mcp_tools_enabled=True,
        write_tool_enabled=True,
        edit_tool_enabled=True,
    )

    # Default MCP server
    servers = {
        "exa": Server(url="https://mcp.exa.ai/mcp"),
    }

    config = AMCPConfig(servers=servers, chat=chat_config)

    # Save configuration
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config_path = save_config(config)

    # Show summary
    console.print("\n" + "=" * 60)
    console.print("[bold green]Configuration Complete![/bold green]")
    console.print(f"\nConfig saved to: {config_path}")
    console.print("\n[bold]Summary:[/bold]")
    console.print(f"  Provider: {provider_id}")
    console.print(f"  Model: {model_id}")
    console.print(f"  Base URL: {base_url}")
    if context_window:
        console.print(f"  Context Window: {context_window:,} tokens")
    if is_custom:
        console.print("  [yellow]⚠ Custom provider (not from models.dev)[/yellow]")

    if not api_key:
        console.print("\n[yellow]Note: API key not set in config.[/yellow]")
        console.print("[dim]Set it via environment variable or add to config file.[/dim]")

    console.print("\n[dim]Run 'amcp' to start chatting![/dim]")

    return config_path


def run_quick_init() -> Path:
    """Run quick initialization without interactive prompts (legacy behavior)."""
    from .config import save_default_config

    return save_default_config()
