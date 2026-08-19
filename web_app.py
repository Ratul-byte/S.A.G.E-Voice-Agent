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
import json
import nest_asyncio
import aiohttp
import requests
import re

from prompts import SAGE_SYSTEM_PROMPT
from tools import TOOL_DEFINITIONS, execute_tool

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

# Model config — override with the GROQ_MODEL env var if you want to switch
# without touching code. Kept in sync with api/index.py (Vercel's entry point).
GROQ_LLM_MODEL = os.environ.get('GROQ_MODEL', 'openai/gpt-oss-20b')


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


def _build_system_content(timezone: str, location: str | None, latitude, longitude) -> str:
    """SAGE's identity plus the user's current time/place context, so it
    doesn't have to ask for information the browser already knows."""
    content = SAGE_SYSTEM_PROMPT + (
        f"\n\nThe user's current browser timezone is {timezone}. "
        "When the user asks for the current date/time without naming a place, "
        "use that timezone with the date/time tool."
    )

    if location:
        content += f" The user's current approximate location is {location}."
    elif latitude is not None and longitude is not None:
        content += (
            f" The user's current approximate coordinates are "
            f"latitude {latitude}, longitude {longitude}."
        )

    if location or (latitude is not None and longitude is not None):
        content += (
            " When the user asks about local weather, time, or other "
            "place-dependent questions without naming a different place, "
            "use this location instead of asking them where they are."
        )

    return content


def llm_generate_reply(
    user_text: str,
    history=None,
    timezone: str = "UTC",
    location: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> str:
    """Generate a reply with conversation context, location awareness, and
    callable SAGE tools (weather, search, calculator, date/time)."""
    api_key = os.environ.get('GROQ_API_KEY', '')
    if not api_key:
        raise ValueError('GROQ_API_KEY not set in environment')

    messages = [
        {
            "role": "system",
            "content": _build_system_content(timezone, location, latitude, longitude),
        }
    ]
    for item in (history or [])[-24:]:
        if isinstance(item, dict) and item.get('role') in ('user', 'assistant') and item.get('content'):
            messages.append({"role": item['role'], "content": str(item['content'])})
    messages.append({"role": "user", "content": user_text})

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    for _ in range(4):
        payload = {
            "model": GROQ_LLM_MODEL,
            "messages": messages,
            "tools": TOOL_DEFINITIONS,
            "tool_choice": "auto",
            "temperature": 0.7,
            "max_tokens": 1024,
        }
        response = requests.post(url, json=payload, headers=headers, timeout=45)
        if response.status_code != 200:
            raise Exception(f"Groq API error: {response.status_code} - {response.text}")
        message = response.json()['choices'][0]['message']
        tool_calls = message.get('tool_calls') or []
        if not tool_calls:
            return (message.get('content') or '').strip()

        # The assistant tool-call message must be replayed before tool results.
        messages.append(message)
        for call in tool_calls:
            name = call['function']['name']
            try:
                arguments = json.loads(call['function'].get('arguments') or '{}')
                result = execute_tool(name, arguments)
            except Exception as exc:
                result = {"error": str(exc)}
            messages.append({
                "role": "tool",
                "tool_call_id": call['id'],
                "content": json.dumps(result, ensure_ascii=False),
            })

    raise RuntimeError('SAGE reached the maximum number of tool calls for this request')


_DEGREE_UNIT_PATTERN = re.compile(r'(-?\d+(?:\.\d+)?)\s*°\s*([CF])\b')
_PERCENT_PATTERN = re.compile(r'(\d+(?:\.\d+)?)\s*%')
_MD_BOLD_PATTERN = re.compile(r'\*\*(.*?)\*\*')
_MD_ITALIC_PATTERN = re.compile(r'(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)')
_MD_HEADER_PATTERN = re.compile(r'^#{1,6}\s*', re.MULTILINE)
_MD_BULLET_PATTERN = re.compile(r'^\s*[-*]\s+', re.MULTILINE)

_UNIT_WORDS = [
    (re.compile(r'\bkm/h\b', re.IGNORECASE), 'kilometers per hour'),
    (re.compile(r'\bkmh\b', re.IGNORECASE), 'kilometers per hour'),
    (re.compile(r'\bmph\b', re.IGNORECASE), 'miles per hour'),
    (re.compile(r'\bm/s\b', re.IGNORECASE), 'meters per second'),
    (re.compile(r'\bhPa\b'), 'hectopascals'),
]

_DEGREE_WORD = {'C': 'degrees Celsius', 'F': 'degrees Fahrenheit'}


def normalize_for_speech(text: str) -> str:
    """Rewrite a reply so ElevenLabs speaks units/symbols/markdown naturally
    (e.g. "36.5 °C" -> "36.5 degrees Celsius", "98%" -> "98 percent").
    This only affects what gets spoken - the chat UI still shows the original
    text with the real symbols/formatting."""
    if not text:
        return text

    result = _DEGREE_UNIT_PATTERN.sub(
        lambda m: f"{m.group(1)} {_DEGREE_WORD[m.group(2).upper()]}", text
    )
    # Any leftover degree symbol (angles, unspecified scale, etc.)
    result = result.replace('°', ' degrees ')
    result = _PERCENT_PATTERN.sub(r'\1 percent', result)

    for pattern, replacement in _UNIT_WORDS:
        result = pattern.sub(replacement, result)

    # Strip markdown formatting so it isn't read out literally.
    result = _MD_BOLD_PATTERN.sub(r'\1', result)
    result = _MD_ITALIC_PATTERN.sub(r'\1', result)
    result = _MD_HEADER_PATTERN.sub('', result)
    result = _MD_BULLET_PATTERN.sub('', result)
    result = result.replace('`', '')

    # Collapse whitespace left behind by the substitutions above.
    result = re.sub(r'[ \t]+', ' ', result)
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result.strip()


def tts_synthesize(text: str) -> bytes:
    """Synthesize text to speech and return audio bytes using ElevenLabs API directly"""
    if not text:
        return b''

    text = normalize_for_speech(text)
    
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

        history = data.get('history', [])
        if not isinstance(history, list):
            history = []
        timezone = data.get('timezone', 'UTC') or 'UTC'
        location = data.get('location') or None
        latitude = data.get('latitude')
        longitude = data.get('longitude')

        # Generate reply with the browser's timezone/location and recent conversation.
        reply = llm_generate_reply(
            user_text,
            history=history,
            timezone=timezone,
            location=location,
            latitude=latitude,
            longitude=longitude,
        )
        return jsonify({'success': True, 'reply': reply})
    
    except Exception as e:
        error_msg = str(e)
        print(f"ERROR in generate_reply: {error_msg}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': error_msg}), 500


@app.route('/api/reset-conversation', methods=['POST'])
def reset_conversation():
    """Conversation memory now lives client-side (sent as `history` with each
    request), so there's nothing to clear server-side - this just exists so
    the frontend's reset call has something to hit."""
    return jsonify({'success': True})


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


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
