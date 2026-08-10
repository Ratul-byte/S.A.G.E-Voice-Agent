import asyncio
import os
import sys
import threading
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import sounddevice as sd
import numpy as np
from typing import List
import base64
from io import BytesIO
import nest_asyncio
import aiohttp

from livekit.plugins import groq, elevenlabs
from livekit.agents.llm.chat_context import ChatContext
from livekit.agents.utils.audio import AudioByteStream
from livekit import rtc

from prompts import SAGE_SYSTEM_PROMPT

# Allow nested event loops (required for Flask threads)
nest_asyncio.apply()

# Load environment variables
def _load_env_multi():
    candidates = []
    if getattr(sys, 'frozen', False):
        candidates.append(os.path.dirname(sys.executable))
    candidates.extend([os.getcwd(), os.path.dirname(__file__)])
    seen = set()
    for d in candidates:
        if not d or d in seen:
            continue
        seen.add(d)
        p = os.path.join(d, '.env')
        if os.path.exists(p):
            load_dotenv(dotenv_path=p)

_load_env_multi()

app = Flask(__name__)
CORS(app)

# Audio configuration
REC_SAMPLE_RATE = 24000
REC_NUM_CHANNELS = 1
REC_DTYPE = 'int16'

# --- Conversation memory --------------------------------------------------
# This is a single-user local assistant (one browser talking to one server
# process), so a simple in-process history is enough to give SAGE context
# across turns - no need for per-session/database complexity.
conversation_history: List[dict] = []
history_lock = threading.Lock()

# Cap how many past turns we send back to the LLM each time, to keep token
# usage/latency bounded. A "turn" here is one user message + one assistant
# reply, so this keeps roughly the last 12 exchanges.
MAX_HISTORY_TURNS = 12


def stt_transcribe_audio_bytes(audio_bytes: bytes) -> str:
    """Transcribe audio bytes using Groq API directly"""
    
    async def _transcribe():
        api_key = os.environ.get('GROQ_API_KEY', '')
        if not api_key:
            raise ValueError('GROQ_API_KEY not set in environment')
        
        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        headers = {
            "Authorization": f"Bearer {api_key}"
        }
        
        async with aiohttp.ClientSession() as session:
            data = aiohttp.FormData()
            data.add_field('file', audio_bytes, filename='audio.wav', content_type='audio/wav')
            data.add_field('model', 'whisper-large-v3-turbo')
            data.add_field('language', 'en')
            
            async with session.post(url, data=data, headers=headers) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise Exception(f"Groq API error: {resp.status} - {error_text}")
                result = await resp.json()
                return result.get('text', '')
    
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(_transcribe())
    except RuntimeError:
        return asyncio.run(_transcribe())


def llm_generate_reply(user_text: str) -> str:
    """Generate LLM reply using Groq, grounded in SAGE's identity and the
    ongoing conversation history so it has context across turns."""
    llm = groq.LLM(model='llama-3.3-70b-versatile')
    chat = ChatContext()

    # SAGE's identity/personality always goes in first, as the system message.
    chat.add_message(role="system", content=SAGE_SYSTEM_PROMPT)

    # Replay recent conversation history so the model has context.
    with history_lock:
        history_snapshot = list(conversation_history)

    for turn in history_snapshot:
        chat.add_message(role=turn['role'], content=turn['content'])

    chat.add_message(role="user", content=user_text)

    async def _generate():
        stream = llm.chat(chat_ctx=chat, tools=[], parallel_tool_calls=False)
        reply: list[str] = []
        try:
            async for chunk in stream:
                if chunk.delta and chunk.delta.content:
                    reply.append(chunk.delta.content)
        finally:
            await stream.aclose()
        return ''.join(reply).strip()
    
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If loop is already running, create a new one
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        reply_text = loop.run_until_complete(_generate())
    except RuntimeError:
        # No event loop in this thread, create one
        reply_text = asyncio.run(_generate())

    # Persist this exchange to memory for future turns, trimming old history
    # so the context sent to the LLM doesn't grow without bound.
    with history_lock:
        conversation_history.append({'role': 'user', 'content': user_text})
        conversation_history.append({'role': 'assistant', 'content': reply_text})
        max_messages = MAX_HISTORY_TURNS * 2
        if len(conversation_history) > max_messages:
            del conversation_history[:len(conversation_history) - max_messages]

    return reply_text


def tts_synthesize(text: str) -> bytes:
    """Synthesize text to speech and return audio bytes using ElevenLabs API directly"""
    if not text:
        return b''
    
    async def _collect():
        api_key = os.environ.get('ELEVEN_API_KEY', '')
        voice_id = os.environ.get('ELEVEN_VOICE_ID', 'EXAVITQu4vr4xnSDxMaL')
        
        if not api_key:
            raise ValueError('ELEVEN_API_KEY not set in environment')
        
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json"
        }
        payload = {
            "text": text,
            "model_id": "eleven_turbo_v2_5",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75
            }
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise Exception(f"ElevenLabs API error: {resp.status} - {error_text}")
                return await resp.read()
    
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If loop is already running, create a new one
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(_collect())
    except RuntimeError:
        # No event loop in this thread, create one
        return asyncio.run(_collect())


@app.route('/')
def index():
    """Serve the main page"""
    return render_template('index.html')


@app.route('/api/transcribe', methods=['POST'])
def transcribe():
    """Transcribe audio from client"""
    try:
        audio_data = request.files['audio'].read()
        
        if not audio_data or len(audio_data) < 100:
            return jsonify({'success': False, 'error': 'Audio too short'}), 400
        
        # Transcribe using Groq API directly
        transcript = stt_transcribe_audio_bytes(audio_data)
        return jsonify({'success': True, 'transcript': transcript})
    
    except Exception as e:
        error_msg = str(e)
        print(f"ERROR in transcribe: {error_msg}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': error_msg}), 500


@app.route('/api/generate-reply', methods=['POST'])
def generate_reply():
    """Generate LLM reply for input text"""
    try:
        data = request.json
        user_text = data.get('text', '').strip()
        
        if not user_text:
            return jsonify({'success': False, 'error': 'No text provided'}), 400
        
        # Generate reply
        reply = llm_generate_reply(user_text)
        return jsonify({'success': True, 'reply': reply})
    
    except Exception as e:
        error_msg = str(e)
        print(f"ERROR in generate_reply: {error_msg}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': error_msg}), 500


@app.route('/api/synthesize-speech', methods=['POST'])
def synthesize_speech():
    """Synthesize text to speech"""
    try:
        data = request.json
        text = data.get('text', '').strip()
        
        if not text:
            return jsonify({'success': False, 'error': 'No text provided'}), 400
        
        # Synthesize
        audio_bytes = tts_synthesize(text)
        
        # Encode to base64 for transmission
        audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')
        
        return jsonify({
            'success': True,
            'audio': audio_b64,
            'sample_rate': REC_SAMPLE_RATE
        })
    
    except Exception as e:
        error_msg = str(e)
        print(f"ERROR in synthesize_speech: {error_msg}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': error_msg}), 500


@app.route('/api/reset-conversation', methods=['POST'])
def reset_conversation():
    """Clear SAGE's conversation memory and start a fresh context."""
    with history_lock:
        conversation_history.clear()
    return jsonify({'success': True})


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
