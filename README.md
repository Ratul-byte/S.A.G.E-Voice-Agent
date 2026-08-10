# SAGE — Voice & Web AI Assistant

**SAGE** is a modern web-based AI assistant that supports both text and voice interaction. It combines conversational memory, real-time voice capabilities, AI reasoning, web access, and practical utility tools into a single assistant.

SAGE uses **Groq/Llama** for language generation, **Groq STT** for speech recognition, and **ElevenLabs** for text-to-speech.

> **SAGE is the assistant's identity.** Llama/Groq are underlying AI services and are not presented as the assistant's name.

---

## Features

### 🧠 Conversation Memory

SAGE keeps track of recent conversation history so follow-up questions understand the previous context instead of behaving like every message starts a new conversation.

- Remembers recent messages in the active conversation
- Sends conversation history with AI requests
- Browser-side history helps preserve context across requests and page reloads
- New conversations can start with cleared history

### 🎙️ Voice Interaction

- Record voice directly from the browser
- Speech is transcribed using Groq STT
- SAGE responds with generated speech using ElevenLabs TTS
- Supports both typed and spoken conversations

### 🤖 SAGE Identity

SAGE consistently introduces itself as **SAGE**.

### 🕐 Date & Time Tool

SAGE can use a real time/date tool instead of guessing the current time.

The system uses the user's browser timezone when available, allowing SAGE to understand the user's local date and time.

It can also answer location-based time questions such as:

- "What time is it?"
- "What's today's date?"
- "What time is it in London?"
- "What is the date in New York?"

### 🌐 Web Search & Browsing

SAGE includes a web-search tool for information that needs current or external knowledge.

The browsing flow is designed to:

1. Create an appropriate search query
2. Search the web
3. Identify relevant results
4. Retrieve readable webpage content
5. Provide that content to SAGE
6. Generate an answer based on the retrieved information

This allows SAGE to handle questions about current events, recent information, websites, and other topics that may be outside the model's built-in knowledge.

### 🧮 Calculator

SAGE has a calculator tool for reliable arithmetic.

Examples:

- `6 × 7`
- `847 × 39`
- `25% of 480`
- `(125 + 75) / 4`

The calculator uses a restricted expression parser rather than executing arbitrary Python code.

### 🌦️ Weather

SAGE can retrieve current weather information for a specified location.

Examples:

- "What's the weather in Dhaka?"
- "Is it raining in London?"
- "What's the temperature in New York?"

### 🗣️ Natural Speech Formatting

SAGE is instructed to convert symbols and operators into natural spoken language when speaking.

Examples:

| Written | Spoken |
|---|---|
| `25°C` | "25 degrees Celsius" |
| `32°F` | "32 degrees Fahrenheit" |
| `6 × 7` | "6 multiplied by 7" |

The displayed response can retain normal symbols while the speech output is normalized for more natural pronunciation.

---

## Technology Stack

- **Python**
- **Flask** — web application/API
- **Groq** — llm and speech-to-text
- **Llama 3.3 70B** — language model
- **Whisper Large-V3** - stt model
- **ElevenLabs** — text-to-speech
- **LiveKit Agents** — voice-agent integration
- **JavaScript** — browser interaction and audio handling
- **HTML/CSS** — web interface
- **Vercel** — production/serverless deployment

---

## Prerequisites

- Windows, Linux, or macOS
- Python 3.13+
- A working microphone and speakers/headphones
- Internet connection
- API keys for the services used by the project

### Environment Variables

Create a `.env` file in the project root:

```env
GROQ_API_KEY=your_groq_api_key_here
ELEVEN_API_KEY=your_elevenlabs_api_key_here
ELEVEN_VOICE_ID=your_elevenlabs_voice_id [optional]
```

Additional environment variables may be required depending on the enabled deployment/tool configuration.

---

## Installation

### 1. Create and activate a virtual environment

Windows PowerShell:

```powershell
python -m venv venv
.\venv\Scripts\activate
```

### 2. Install dependencies

```powershell
pip install -r requirements.txt
```

### 3. Configure environment variables

Create `.env` and add the required API keys.

### 4. Run the web application

```powershell
python web_app.py
```

The local application should be available at:

```text
http://localhost:5000
```

---

## Usage

1. Open SAGE in your browser.
2. Type a message or use the microphone.
3. Send the message.
4. SAGE maintains the current conversation context.
5. If a question requires a tool, SAGE can use the appropriate tool.
6. Enable voice playback to hear SAGE's response.
7. Use the volume control to adjust spoken response volume.

### Example Questions

```text
Hello, who are you?

What time is it?

What time is it in Tokyo?

What's 847 multiplied by 39?

What's the weather in Dhaka?

Search the web for the latest AI news.

Who won the latest major football match?

What does this website say about its services?
```

---

## API Endpoints

### `GET /`

Loads the SAGE web interface.

### `POST /api/transcribe`

Transcribes uploaded audio using speech-to-text.

### `POST /api/generate-reply`

Generates an AI response using the conversation history and available tools.

### `POST /api/synthesize-speech`

Converts SAGE's response into spoken audio using ElevenLabs.

---

## Project Structure

```text
SAGE/
├── web_app.py              # Main Flask web application
├── agent.py                # LiveKit voice-agent integration
├── app.py                  # Original application entry point
├── api/
│   └── index.py            # Vercel/serverless API
├── prompts.py              # SAGE identity, behavior, and tool instructions
├── tools.py                # Assistant tools
├── templates/
│   └── index.html          # Web interface
├── static/
│   ├── app.js              # Frontend logic, audio, memory, and controls
│   └── style.css           # Interface styling
├── requirements.txt        # Python dependencies
├── vercel.json             # Vercel configuration
└── .env                    # Local secrets (not committed)
```

---

## Memory Architecture

SAGE uses conversation history as part of the request sent to the language model.

```text
User message
     ↓
Browser conversation history
     ↓
/api/generate-reply
     ↓
Conversation context + current message
     ↓
SAGE / Llama
     ↓
Tool call when required
     ↓
Final response
```

For serverless deployment, the browser-side conversation history is especially important because serverless functions should not be relied upon to maintain permanent in-memory state between requests.

---

## Tool Architecture

SAGE's tool system follows a simple pattern:

```text
                 ┌──────────┐
                 │   SAGE   │
                 └────┬─────┘
                      │
              Does this need
                 a tool?
                      │
        ┌─────────────┼─────────────┐
        ↓             ↓             ↓
      Time          Search       Calculator
        │             │             │
        └─────────────┼─────────────┘
                      ↓
                Tool result
                      ↓
                 SAGE response
```

This makes it possible to add additional tools later without changing SAGE's core conversational behavior.

---

## Browser Support

Modern versions of:

- Chrome / Chromium
- Microsoft Edge
- Firefox
- Safari

Microphone access requires browser permission and generally requires a secure context such as HTTPS when deployed.

---

## Troubleshooting

### Microphone does not work

- Check browser microphone permissions.
- Make sure the correct microphone is selected.
- Verify the microphone works in another application.
- Use HTTPS when required by the browser.

### No AI response

- Verify `GROQ_API_KEY`.
- Check the browser developer console.
- Check the server/Vercel logs.
- Verify the request to `/api/generate-reply` is returning successfully.

### No voice response

- Verify `ELEVEN_API_KEY`.
- Verify `ELEVEN_VOICE_ID`.
- Check browser audio permissions.
- Check the SAGE volume control.

---

## Production Deployment

SAGE can be deployed as a web application and the API can be hosted through Vercel.

Before deploying:

1. Configure all required environment variables in the hosting platform.
2. Confirm the serverless API entry point is correctly configured.
3. Test `/api/generate-reply`.
4. Test speech transcription.
5. Test speech synthesis.
6. Test the tool system.
7. Test the browser timezone.
8. Test the volume control.

Never commit API keys or `.env` files to source control.

---

## Future Tooling

The current tool system is intentionally expandable. Potential future tools include:

- Timezone conversion
- Unit conversion
- Maps and places
- File/document reading
- Image understanding
- Long-term memory
- Email
- Calendar
- GitHub
- Task management
- Cloud storage
- Image generation

---

## License

MIT
