import asyncio
import os
import sys
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

import base64
from io import BytesIO

try:
    import nest_asyncio
    nest_asyncio.apply()
except:
    pass

try:
    import aiohttp
except ImportError:
    print("WARNING: aiohttp not installed")

try:
    from livekit.plugins import groq, elevenlabs
    from livekit.agents.llm.chat_context import ChatContext
except ImportError as e:
    print(f"WARNING: LiveKit imports failed: {e}")

# Get absolute paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, 'static')
TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates')

print(f"BASE_DIR: {BASE_DIR}")
print(f"TEMPLATE_DIR: {TEMPLATE_DIR}")
print(f"STATIC_DIR: {STATIC_DIR}")

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
    """Generate LLM reply using Groq"""
    llm = groq.LLM(model='llama-3.3-70b-versatile')
    chat = ChatContext()
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
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(_generate())
    except RuntimeError:
        return asyncio.run(_generate())


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
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(_collect())
    except RuntimeError:
        return asyncio.run(_collect())


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
