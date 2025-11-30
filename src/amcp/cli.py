from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.json import JSON
from rich.panel import Panel
from rich.markdown import Markdown

from .config import AMCPConfig, load_config, save_default_config, save_config, Server
from .mcp_client import call_mcp_tool, list_mcp_tools

from .agent import Agent
from .agent_spec import load_agent_spec, get_default_agent_spec, list_available_agents

app = typer.Typer(add_completion=False, context_settings={"help_option_names": ["-h", "--help"]})
console = Console()


@app.command(help="Initialize default config at ~/.config/amcp/config.toml if missing")
def init() -> None:
    path = save_default_config()
    console.print(f"Wrote default config to {path}")


mcp = typer.Typer(help="MCP utilities (stdio client)")
app.add_typer(mcp, name="mcp")


@mcp.command("tools", help="List tools from a configured MCP server")
def mcp_tools(server: Annotated[str, typer.Option("--server", "-s")]):
    cfg: AMCPConfig = load_config()
    if server not in cfg.servers:
        raise typer.BadParameter(f"Unknown server: {server}")
    tools = asyncio.run(list_mcp_tools(cfg.servers[server]))
    console.print(JSON.from_data(tools))


@mcp.command("call", help="Call a tool on a configured MCP server")
def mcp_call(
    server: Annotated[str, typer.Option("--server", "-s")],
    tool: Annotated[str, typer.Option("--tool", "-t")],
    args: Annotated[str | None, typer.Option("--args", help="JSON-encoded arguments")]=None,
):
    cfg: AMCPConfig = load_config()
    if server not in cfg.servers:
        raise typer.BadParameter(f"Unknown server: {server}")
    arguments = json.loads(args) if args else {}
    resp = asyncio.run(call_mcp_tool(cfg.servers[server], tool, arguments))
    console.print(JSON.from_data(resp))


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    message: Annotated[str | None, typer.Option("--once", help="Send one message and exit")] = None,
    agent_file: Annotated[str | None, typer.Option("--agent", help="Path to agent specification file")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir", "-w", help="Set working directory", exists=True, file_okay=False, dir_okay=True, readable=True)] = None,
    no_progress: Annotated[bool, typer.Option("--no-progress", help="Disable progress indicators")] = False,
    list_agents: Annotated[bool, typer.Option("--list", help="List available agent specifications")] = False,
    session_id: Annotated[str | None, typer.Option("--session", help="Use specific session ID for conversation continuity")] = None,
    clear_session: Annotated[bool, typer.Option("--clear", help="Clear conversation history for the session")] = False,
    list_sessions: Annotated[bool, typer.Option("--list-sessions", help="List available conversation sessions")] = False,
) -> None:
    """Enhanced agent chat with improved tool management and context awareness."""
    
    # If a subcommand is invoked, don't run the agent
    if ctx.invoked_subcommand is not None:
        return
    
    # Handle session listing
    if list_sessions:
        sessions_dir = Path.home() / ".config" / "amcp" / "sessions"
        if not sessions_dir.exists():
            console.print("[yellow]No sessions directory found[/yellow]")
            return
        
        session_files = list(sessions_dir.glob("*.json"))
        if not session_files:
            console.print("[yellow]No conversation sessions found[/yellow]")
            return
        
        console.print("[bold]Available Conversation Sessions:[/bold]")
        for session_file in sorted(session_files, key=lambda f: f.stat().st_mtime, reverse=True):
            try:
                with open(session_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    console.print(f"📄 {data.get('session_id', session_file.stem)}")
                    console.print(f"   Agent: {data.get('agent_name', 'Unknown')}")
                    console.print(f"   Messages: {len(data.get('conversation_history', []))}")
                    console.print(f"   Created: {data.get('created_at', 'Unknown')}")
                    console.print(f"   File: {session_file}")
                    console.print()
            except Exception as e:
                console.print(f"❌ {session_file.name}: {e}")
        return
    
    if list_agents:
        # Check both global config dir and local agents dir
        agents_dir = Path(os.path.expanduser("~/.config/amcp/agents"))
        local_agents_dir = Path("agents")
        
        agent_files = list_available_agents(agents_dir)
        local_agent_files = list_available_agents(local_agents_dir)
        
        # Combine both lists
        all_agent_files = agent_files + local_agent_files
        
        if not all_agent_files:
            console.print("[yellow]No agent specifications found. Create one in ~/.config/amcp/agents/ or local agents/[/yellow]")
            return
        
        console.print("[bold]Available Agent Specifications:[/bold]")
        for agent_file in all_agent_files:
            try:
                spec = load_agent_spec(agent_file)
                console.print(f"📄 {agent_file.name}")
                console.print(f"   Name: {spec.name}")
                console.print(f"   Description: {spec.description}")
                console.print(f"   Tools: {len(spec.tools)}")
                console.print()
            except Exception as e:
                console.print(f"❌ {agent_file.name}: {e}")
        
        # Also show default agent
        default_spec = get_default_agent_spec()
        console.print("[bold]Default Agent:[/bold]")
        console.print(f"   Name: {default_spec.name}")
        console.print(f"   Description: {default_spec.description}")
        console.print(f"   Tools: {len(default_spec.tools)}")
        return
    
    try:
        # Load agent specification
        if agent_file:
            agent_path = Path(agent_file).expanduser()
            if not agent_path.exists():
                console.print(f"[red]Agent file not found: {agent_path}[/red]")
                raise typer.Exit(1)
            agent_spec = load_agent_spec(agent_path)
            console.print(f"[green]Loaded agent: {agent_spec.name}[/green]")
        else:
            agent_spec = get_default_agent_spec()
            console.print(f"[green]Using default agent: {agent_spec.name}[/green]")
        
        # Create agent with session management
        agent = Agent(agent_spec, session_id=session_id)
        
        # Handle session clearing
        if clear_session:
            agent.clear_conversation_history()
            console.print(f"[green]Cleared conversation history for session: {agent.session_id}[/green]")
        
        # Show session info
        session_info = agent.get_conversation_summary()
        if session_info['message_count'] > 0:
            console.print(f"[dim]Session {agent.session_id}: {session_info['message_count']} messages in history[/dim]")
        else:
            console.print(f"[dim]New session started: {agent.session_id}[/dim]")
        
        if message is not None:
            # Single message mode
            console.print(f"[bold]🤖 Agent {agent.name}[/bold] - Processing...")
            response = asyncio.run(agent.run(
                user_input=message,
                work_dir=work_dir,
                stream=False,
                show_progress=not no_progress
            ))
            
            console.print(Panel(Markdown(response), title=f"Agent {agent.name}", border_style="cyan"))
            
            # Show execution summary
            summary = agent.get_execution_summary()
            console.print(f"[dim]Steps: {summary['steps_taken']}/{summary['max_steps']} | Tools called: {summary['tools_called']}[/dim]")
            
        else:
            # Interactive mode
            console.print(f"[bold]🤖 Agent {agent.name} - Interactive Mode[/bold]")
            console.print(f"[dim]Description: {agent_spec.description}[/dim]")
            console.print(f"[dim]Max steps: {agent_spec.max_steps} | Session: {agent.session_id}[/dim]")
            console.print(f"[dim]Commands: 'exit' to quit, 'clear' to clear history, 'info' for session info[/dim]")
            console.print()
            
            while True:
                try:
                    user_input = console.input("[bold]You:[/bold] ").strip()
                    
                    if user_input.lower() in ['exit', 'quit', 'q']:
                        console.print("[green]Goodbye! 👋[/green]")
                        break
                    
                    if user_input.lower() == 'clear':
                        agent.clear_conversation_history()
                        console.print(f"[green]Conversation history cleared for session: {agent.session_id}[/green]")
                        continue
                    
                    if user_input.lower() == 'info':
                        session_info = agent.get_conversation_summary()
                        console.print(f"[bold]Session Info:[/bold]")
                        console.print(f"Session ID: {session_info['session_id']}")
                        console.print(f"Agent: {session_info['agent_name']}")
                        console.print(f"Messages: {session_info['message_count']}")
                        console.print(f"Tool calls: {session_info['tool_calls_count']}")
                        console.print(f"Session file: {session_info['session_file']}")
                        console.print()
                        continue
                    
                    if not user_input:
                        continue
                    
                    console.print(f"[bold]🤖 Agent {agent.name}[/bold] - Processing...")
                    response = asyncio.run(agent.run(
                        user_input=user_input,
                        work_dir=work_dir,
                        stream=False,
                        show_progress=not no_progress
                    ))
                    
                    console.print(Panel(Markdown(response), title=f"Agent {agent.name}", border_style="cyan"))
                    
                    # Show execution summary
                    summary = agent.get_execution_summary()
                    console.print(f"[dim]Steps: {summary['steps_taken']}/{summary['max_steps']} | Tools called: {summary['tools_called']} | Session: {agent.session_id}[/dim]")
                    console.print()
                    
                except KeyboardInterrupt:
                    console.print("\\n[yellow]Interrupted. Type 'exit' to quit.[/yellow]")
                except Exception as e:
                    console.print(f"[red]Error: {e}[/red]")
                    console.print()
    
    except Exception as e:
        console.print(f"[red]Agent failed:[/red] {e}")
        raise typer.Exit(code=1)


@app.command(help="Enhanced agent chat (alias for default command)")

@app.command(help="Enhanced agent chat (alias for default command)")
def agent(
    ctx: typer.Context,
    message: Annotated[str | None, typer.Option("--once", help="Send one message and exit")] = None,
    agent_file: Annotated[str | None, typer.Option("--agent", help="Path to agent specification file")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir", "-w", help="Set working directory", exists=True, file_okay=False, dir_okay=True, readable=True)] = None,
    no_progress: Annotated[bool, typer.Option("--no-progress", help="Disable progress indicators")] = False,
    list_agents: Annotated[bool, typer.Option("--list", help="List available agent specifications")] = False,
    session_id: Annotated[str | None, typer.Option("--session", help="Use specific session ID for conversation continuity")] = None,
    clear_session: Annotated[bool, typer.Option("--clear", help="Clear conversation history for the session")] = False,
    list_sessions: Annotated[bool, typer.Option("--list-sessions", help="List available conversation sessions")] = False,
) -> None:
    """Enhanced agent chat (alias for default command)."""
    ctx.invoke(main, message=message, agent_file=agent_file, work_dir=work_dir, 
               no_progress=no_progress, list_agents=list_agents, session_id=session_id,
               clear_session=clear_session, list_sessions=list_sessions)



if __name__ == "__main__":
    app()
