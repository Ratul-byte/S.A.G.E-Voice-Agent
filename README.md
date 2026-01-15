# VTC Playground - Web Version

A modern web-based AI assistant that supports text input and voice interaction. Uses LiveKit Agents plugins (Groq STT/LLM, ElevenLabs TTS) for intelligent conversation.

## Features

- **Text Input**: Type messages directly into the interface
- **Voice Input**: Record audio and automatically transcribe using Groq STT
- **AI Responses**: Get intelligent replies powered by Groq LLM (Llama 3.3-70b)
- **Text-to-Speech**: Hear AI responses synthesized with ElevenLabs TTS
- **Responsive Design**: Works on desktop and mobile browsers

## Prerequisites

- Windows/Linux/Mac with Python 3.13+
- Microphone and speakers
- API keys in `.env` file:
  - `GROQ_API_KEY` (required)
  - `ELEVEN_API_KEY` (required)
  - `ELEVEN_VOICE_ID` (optional, defaults to a preset voice)

## Installation & Setup

### 1. Activate the Virtual Environment

```powershell
cd VTC
.\vc_agent\Scripts\activate
```

### 2. Install Requirements

```powershell
pip install -r requirement.txt
```

### 3. Configure Environment

Create a `.env` file in the `VTC` folder:

```
GROQ_API_KEY=your_groq_api_key_here
ELEVEN_API_KEY=your_eleven_api_key_here
ELEVEN_VOICE_ID=EXAVITQu4vr4xnSDxMaL
```

### 4. Run the Web Server

```powershell
python web_app.py
```

The app will be available at `http://localhost:5000`

## Usage

1. **Open Browser**: Navigate to `http://localhost:5000`
2. **Text Input**: Type a message or use the microphone button to record
3. **Send**: Click "Send" to submit your message
4. **View Reply**: The AI response appears in the Reply section
5. **Audio**: Enable "Speak Reply" to hear the response, or click "Play Audio Reply" to replay it

## Browser Support

- Chrome/Chromium 60+
- Firefox 55+
- Safari 12+
- Edge 79+

## API Endpoints

- `GET /` - Main page
- `POST /api/transcribe` - Transcribe audio to text
- `POST /api/generate-reply` - Generate AI response
- `POST /api/synthesize-speech` - Convert text to speech

## Deployment

### Local Network Access

Modify the last line of `web_app.py`:

```python
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
```

Then access from other devices using: `http://<your-ip>:5000`

### Production Deployment

For production, use a production WSGI server:

```powershell
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 web_app:app
```

Or use Waitress:

```powershell
pip install waitress
waitress-serve --host=0.0.0.0 --port=5000 web_app:app
```

## Troubleshooting

### Microphone Not Working
- Check browser microphone permissions
- Verify microphone is set as default in Windows Sound settings
- Test microphone with other apps first

### No AI Response
- Verify API keys are correct in `.env`
- Check internet connection (APIs are cloud-based)
- Review browser console for errors (F12)

### Audio Playback Issues
- Ensure speakers are enabled and working
- Check browser audio settings
- Try a different browser

## File Structure

```
VTC/
├── web_app.py              # Flask server
├── templates/
│   └── index.html          # Web interface
├── static/
│   ├── app.js              # Frontend logic
│   └── style.css           # Styling
├── agent.py                # Original agent (not used in web)
├── app.py                  # Original desktop app (not used in web)
├── db_driver.py            # Database utilities
├── prompts.py              # Prompt templates
├── requirement.txt         # Python dependencies
└── .env                    # API keys (create this)
```

## Development

To enable debug mode and auto-reload:

```python
app.run(debug=True, host='localhost', port=5000)
```

## License

MIT
