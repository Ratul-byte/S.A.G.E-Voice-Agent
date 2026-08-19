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

load_dotenv(dotenv_path=".env")

@function_tool
async def lookup_weather(
    context: RunContext,
    location: str,
):
    """Used to look up weather information."""

    return {"weather": "sunny", "temperature": 70}


async def entrypoint(ctx: JobContext):
    await ctx.connect()

    agent = Agent(
        instructions=AGENT_INSTRUCTION,
        tools=[lookup_weather],
    )
    session = AgentSession(
        vad=silero.VAD.load(),
        # any combination of STT, LLM, TTS, or realtime API can be used
        stt=groq.STT(),  
        llm=groq.LLM(model="openai/gpt-oss-20b"),
        tts=elevenlabs.TTS(voice_id="EXAVITQu4vr4xnSDxMaL"), 
    )

    #await session.start(agent=agent, room=ctx.room)
    await session.generate_reply(instructions=WELCOME_MESSAGE)
    await session.say(WELCOME_MESSAGE)

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))