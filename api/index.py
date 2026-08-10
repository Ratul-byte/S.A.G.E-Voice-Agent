import asyncio
import os
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import base64
import aiohttp
import sys

# Make the project root importable in local and serverless environments.
sys.path.insert(0, BASE_DIR) if "BASE_DIR" in globals() else None

# Load environment variables
load_dotenv()

# Get absolute paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
from prompts import SAGE_SYSTEM_PROMPT

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


def llm_generate_reply(user_text: str, client_history=None) -> str:
    """Generate a SAGE reply with the ongoing conversation context."""

    api_key = os.environ.get('GROQ_API_KEY', '')
    if not api_key:
        raise ValueError('GROQ_API_KEY not set in environment')

    import requests
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    messages = [{"role": "system", "content": SAGE_SYSTEM_PROMPT}]

    # The browser keeps the conversation context so this also works when the
    # API runs as a stateless/serverless function.
    if isinstance(client_history, list):
        for item in client_history[-24:]:
            if not isinstance(item, dict):
                continue
            role = item.get('role')
            content = item.get('content', '')
            if role in ('user', 'assistant') and isinstance(content, str) and content.strip():
                messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": user_text})

    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 1024
    }

    response = requests.post(url, headers=headers, json=payload)
    if response.status_code != 200:
        raise Exception(f"Groq API error: {response.status_code} - {response.text}")
    result = response.json()
    return result['choices'][0]['message']['content'].strip()


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
        
        if not user_text:
            return jsonify({'success': False, 'error': 'No text provided'}), 400
        
        # Generate reply
        reply = llm_generate_reply(user_text, client_history)
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


@app.route('/api/reset-conversation', methods=['POST'])
def reset_conversation():
    """Reset endpoint kept for compatibility; browser memory is client-side."""
    return jsonify({'success': True})
