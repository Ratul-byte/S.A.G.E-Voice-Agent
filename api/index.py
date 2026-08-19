import asyncio
import os
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import base64
import aiohttp
import json
import requests

from prompts import SAGE_SYSTEM_PROMPT
from tools import TOOL_DEFINITIONS, execute_tool

# Load environment variables
load_dotenv()

# Get absolute paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, 'static')
TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates')

app = Flask(__name__, 
    static_folder=STATIC_DIR,
    static_url_path='/static',
    template_folder=TEMPLATE_DIR
)
CORS(app)

# Audio configuration
REC_SAMPLE_RATE = 24000
REC_NUM_CHANNELS = 1
REC_DTYPE = 'int16'


# Model config — override with the GROQ_MODEL env var if you want to switch
# without touching code. api/index.py is Vercel's actual serverless entry
# point (see vercel.json), and is a standalone implementation separate from
# web_app.py/agent.py/etc, so it needs its own copy of this.
GROQ_LLM_MODEL = os.environ.get('GROQ_MODEL', 'openai/gpt-oss-20b')


def stt_transcribe_audio_bytes(audio_bytes: bytes) -> str:
    """Transcribe audio bytes using Groq API directly"""
    
    api_key = os.environ.get('GROQ_API_KEY', '')
    if not api_key:
        raise ValueError('GROQ_API_KEY not set in environment')
    
    import requests
    url = "https://api.groq.com/openai/v1/audio/transcriptions"
    headers = {
        "Authorization": f"Bearer {api_key}"
    }
    files = {
        'file': ('audio.wav', audio_bytes, 'audio/wav'),
    }
    data = {
        'model': 'whisper-large-v3-turbo',
        'language': 'en',
    }
    
    response = requests.post(url, headers=headers, files=files, data=data)
    if response.status_code != 200:
        raise Exception(f"Groq API error: {response.status_code} - {response.text}")
    result = response.json()
    return result.get('text', '')


def llm_generate_reply(
    user_text: str,
    history=None,
    timezone: str = "UTC",
    location: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> str:
    """Generate a reply with conversation context and callable SAGE tools."""
    api_key = os.environ.get('GROQ_API_KEY', '')
    if not api_key:
        raise ValueError('GROQ_API_KEY not set in environment')

    system_content = (
        SAGE_SYSTEM_PROMPT
        + f"\n\nThe user's current browser timezone is {timezone}. When the user asks for the current date/time without naming a place, use that timezone with the date/time tool."
    )
    if location:
        system_content += f" The user's current approximate location is {location}."
    elif latitude is not None and longitude is not None:
        system_content += f" The user's current approximate coordinates are latitude {latitude}, longitude {longitude}."
    if location or (latitude is not None and longitude is not None):
        system_content += (
            " When the user asks about local weather, time, or other place-dependent "
            "questions without naming a different place, use this location instead of "
            "asking them where they are."
        )

    messages = [
        {
            "role": "system",
            "content": system_content,
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


def tts_synthesize(text: str) -> bytes:
    """Synthesize text to speech and return audio bytes using ElevenLabs API directly"""
    if not text:
        return b''
    
    api_key = os.environ.get('ELEVEN_API_KEY', '')
    voice_id = os.environ.get('ELEVEN_VOICE_ID', 'EXAVITQu4vr4xnSDxMaL')
    
    if not api_key:
        raise ValueError('ELEVEN_API_KEY not set in environment')
    
    import requests
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
    
    response = requests.post(url, json=payload, headers=headers)
    if response.status_code != 200:
        raise Exception(f"ElevenLabs API error: {response.status_code} - {response.text}")
    return response.content


@app.route('/')
def index():
    """Serve the main page"""
    try:
        return render_template('index.html')
    except Exception as e:
        print(f"ERROR: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/health')
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok'})


@app.route('/api/transcribe', methods=['POST'])
def transcribe():
    """Transcribe audio from client"""
    try:
        if 'audio' not in request.files:
            return jsonify({'success': False, 'error': 'No audio file provided'}), 400
            
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
        if not data:
            return jsonify({'success': False, 'error': 'No JSON data'}), 400
            
        user_text = data.get('text', '').strip()
        history = data.get('history', [])
        timezone = data.get('timezone', 'UTC') or 'UTC'
        location = data.get('location') or None
        latitude = data.get('latitude')
        longitude = data.get('longitude')

        if not user_text:
            return jsonify({'success': False, 'error': 'No text provided'}), 400

        if not isinstance(history, list):
            history = []

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
    """Conversation memory lives client-side (sent as `history` with each
    request) since Vercel serverless instances aren't persistent - this just
    exists so the frontend's reset call has something to hit."""
    return jsonify({'success': True})


@app.route('/api/synthesize-speech', methods=['POST'])
def synthesize_speech():
    """Synthesize text to speech"""
    try:
        data = request.json
        if not data:
            return jsonify({'success': False, 'error': 'No JSON data'}), 400
            
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
            'sample_rate': 24000
        })
    
    except Exception as e:
        error_msg = str(e)
        print(f"ERROR in synthesize_speech: {error_msg}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': error_msg}), 500