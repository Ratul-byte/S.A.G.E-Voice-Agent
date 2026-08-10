from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    RunContext,
    WorkerOptions,
    cli,
    function_tool,
)
from livekit.plugins import groq, silero, openai, elevenlabs
from prompts import AGENT_INSTRUCTION, WELCOME_MESSAGE
from dotenv import load_dotenv
from tools import execute_tool

load_dotenv(dotenv_path=".env")

@function_tool
async def get_current_datetime(context: RunContext, timezone: str) -> dict:
    """Get the exact current local date and time. Use an IANA timezone such as Asia/Dhaka or America/New_York."""
    return await asyncio.to_thread(execute_tool, "get_current_datetime", {"timezone": timezone})


@function_tool
async def web_search(context: RunContext, query: str) -> dict:
    """Search the public web for current information."""
    return await asyncio.to_thread(execute_tool, "web_search", {"query": query})


@function_tool
async def calculator(context: RunContext, expression: str) -> dict:
    """Calculate an arithmetic expression accurately."""
    return await asyncio.to_thread(execute_tool, "calculator", {"expression": expression})


@function_tool
async def get_weather(context: RunContext, location: str) -> dict:
    """Get current weather and today's forecast for a location."""
    return await asyncio.to_thread(execute_tool, "get_weather", {"location": location})



async def entrypoint(ctx: JobContext):
    await ctx.connect()

    agent = Agent(
        instructions=AGENT_INSTRUCTION,
        tools=[get_current_datetime, web_search, calculator, get_weather],
    )
    session = AgentSession(
        vad=silero.VAD.load(),
        # any combination of STT, LLM, TTS, or realtime API can be used
        stt=groq.STT(),  
        llm=groq.LLM(model="llama-3.3-70b-versatile"),
        tts=elevenlabs.TTS(voice_id="EXAVITQu4vr4xnSDxMaL"), 
    )

    #await session.start(agent=agent, room=ctx.room)
    await session.generate_reply(instructions=WELCOME_MESSAGE)
    await session.say(WELCOME_MESSAGE)

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))