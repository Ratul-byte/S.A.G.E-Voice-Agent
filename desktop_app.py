import os
import asyncio
import tempfile
import wave
import time
from typing import Optional

import PySimpleGUI as sg
import sounddevice as sd
import numpy as np
from dotenv import load_dotenv

from livekit import rtc
from livekit.agents.llm.chat_context import ChatContext
from livekit.plugins import groq, elevenlabs
from livekit.agents.utils import AudioByteStream

# Load environment variables
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

GROQ_MODEL = os.getenv("GROQ_MODEL", "meta-llama/llama-prompt-guard-2-22m")
ELEVEN_VOICE_ID = os.getenv("ELEVEN_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")
REC_SAMPLE_RATE = 24000  # Match OpenAI/Groq STT expected sample rate
REC_CHANNELS = 1


def record_audio(seconds: Optional[float] = None) -> np.ndarray:
    """
    Record audio from the default microphone.
    If seconds is None, records until the user releases the button (handled externally).
    Returns int16 numpy array of shape (n_samples, channels).
    """
    duration = seconds or 5.0
    dtype = np.int16
    frames = sd.rec(int(duration * REC_SAMPLE_RATE), samplerate=REC_SAMPLE_RATE, channels=REC_CHANNELS, dtype=dtype)
    sd.wait()
    return frames


def audio_frames_from_numpy(audio_np: np.ndarray, sample_rate: int, num_channels: int) -> list[rtc.AudioFrame]:
    """
    Convert a numpy int16 array to LiveKit rtc.AudioFrame list using fixed chunking.
    """
    bstream = AudioByteStream(sample_rate=sample_rate, num_channels=num_channels, samples_per_channel=sample_rate // 20)  # 50ms chunks
    bytes_data = audio_np.tobytes()
    frames = bstream.write(bytes_data)
    frames.extend(bstream.flush())
    return frames


async def transcribe_audio(frames: list[rtc.AudioFrame]) -> str:
    stt = groq.STT(model="whisper-large-v3-turbo")
    # Recognize expects an AudioBuffer (list[AudioFrame] is valid)
    event = await stt.recognize(frames)
    if event.alternatives:
        return event.alternatives[0].text
    return ""


async def generate_reply_text(system_prompt: str, user_text: str) -> str:
    llm = groq.LLM(model=GROQ_MODEL)
    chat_ctx = ChatContext.empty()
    if system_prompt:
        chat_ctx.add_message(role="system", content=system_prompt)
    chat_ctx.add_message(role="user", content=user_text)

    stream = llm.chat(chat_ctx=chat_ctx, tools=[])
    full_text = ""
    async for chunk in stream:
        if chunk.delta and chunk.delta.content:
            full_text += chunk.delta.content
    return full_text.strip()


async def synthesize_tts(text: str) -> rtc.AudioFrame:
    tts = elevenlabs.TTS(voice_id=ELEVEN_VOICE_ID)
    stream = tts.synthesize(text)
    # Collect to a single AudioFrame
    frame = await stream.collect()
    return frame


def play_audio_frame(frame: rtc.AudioFrame) -> None:
    """
    Write the audio frame to a temp wav and play via winsound for reliability on Windows.
    """
    import winsound

    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
        tmp_path = tmp.name
        with wave.open(tmp, "wb") as wf:
            wf.setnchannels(frame.num_channels)
            wf.setsampwidth(2)
            wf.setframerate(frame.sample_rate)
            # frame.data is a memoryview/bytes-like of int16 PCM
            wf.writeframes(frame.data.tobytes())
    # Async playback
    winsound.PlaySound(tmp_path, winsound.SND_FILENAME | winsound.SND_ASYNC)


def build_gui():
    sg.theme("SystemDefault")
    layout = [
        [sg.Text("LiveKit-like Assistant"), sg.Push(), sg.Button("Exit", key="-EXIT-")],
        [sg.Multiline(key="-LOG-", size=(80, 20), disabled=True, autoscroll=True)],
        [sg.Input(key="-TEXT-", size=(60,1)), sg.Button("Send", key="-SEND-")],
        [sg.Button("Hold to Talk", key="-MIC-", button_color=("white", "orange"), size=(15,1))],
        [sg.Checkbox("Speak responses", key="-SPEAK-", default=True)],
    ]
    return sg.Window("VTC Assistant", layout, finalize=True)


def append_log(win: sg.Window, text: str):
    prev = win["-LOG-"].get()
    win["-LOG-"].update(prev + ("\n" if prev else "") + text)


def main():
    # Optionally load system prompt
    system_prompt = ""
    try:
        from prompts import AGENT_INSTRUCTION
        system_prompt = AGENT_INSTRUCTION.strip()
    except Exception:
        pass

    win = build_gui()

    recording = False
    mic_start_ts = 0.0
    mic_buffer = None

    while True:
        event, values = win.read(timeout=50)
        if event in (sg.WIN_CLOSED, "-EXIT-"):
            break

        if event == "-SEND-":
            user_text = values.get("-TEXT-", "").strip()
            if not user_text:
                continue
            append_log(win, f"You: {user_text}")
            try:
                reply = asyncio.run(generate_reply_text(system_prompt, user_text))
                append_log(win, f"Assistant: {reply}")
                if values.get("-SPEAK-") and reply:
                    frame = asyncio.run(synthesize_tts(reply))
                    play_audio_frame(frame)
            except Exception as e:
                append_log(win, f"Error: {e}")

        # Simulate hold-to-talk: press => start recording, release => stop
        if event == "-MIC-":
            if not recording:
                recording = True
                mic_start_ts = time.time()
                append_log(win, "Listening...")
                # Start short recording (we'll keep it simple: fixed 8s)
                mic_buffer = record_audio(seconds=8.0)
                # Stop and process
                recording = False
                try:
                    frames = audio_frames_from_numpy(mic_buffer, REC_SAMPLE_RATE, REC_CHANNELS)
                    transcript = asyncio.run(transcribe_audio(frames))
                    if transcript:
                        append_log(win, f"You (voice): {transcript}")
                        reply = asyncio.run(generate_reply_text(system_prompt, transcript))
                        append_log(win, f"Assistant: {reply}")
                        if values.get("-SPEAK-") and reply:
                            frame = asyncio.run(synthesize_tts(reply))
                            play_audio_frame(frame)
                    else:
                        append_log(win, "(No speech detected)")
                except Exception as e:
                    append_log(win, f"Error: {e}")

    win.close()


if __name__ == "__main__":
    main()
