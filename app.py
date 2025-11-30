import gradio as gr
import asyncio
from src.amcp.agent import Agent
from src.amcp.agent_spec import get_default_agent_spec

async def chat(message, history):
    """Process chat message with AMCP agent."""
    agent = Agent(agent_spec=get_default_agent_spec())
    
    try:
        response = await agent.run(
            user_input=message,
            stream=False,
            show_progress=False
        )
        return response
    except Exception as e:
        return f"Error: {str(e)}"

def chat_wrapper(message, history):
    """Sync wrapper for async chat function."""
    return asyncio.run(chat(message, history))

# Create Gradio interface
demo = gr.ChatInterface(
    fn=chat_wrapper,
    title="AMCP - Agent CLI",
    description="A Lego-style coding agent with built-in tools (read_file, grep, bash, think)",
    examples=[
        "List files in the current directory",
        "Search for 'def' in Python files",
        "What tools do you have available?"
    ]
)

if __name__ == "__main__":
    demo.launch()
