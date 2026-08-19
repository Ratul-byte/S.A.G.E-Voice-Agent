import asyncio
import threading
import queue
import os
import sys
from typing import List

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import sounddevice as sd
import numpy as np
from dotenv import load_dotenv

from livekit.plugins import groq, elevenlabs
from livekit.agents.llm.chat_context import ChatContext
from livekit.agents.utils.audio import AudioByteStream
from livekit import rtc

# Load environment variables from .env next to the exe (PyInstaller) or source
def _load_env_multi():
    candidates = []
    # When frozen by PyInstaller, prefer the directory of the executable
    if getattr(sys, 'frozen', False):
        candidates.append(os.path.dirname(sys.executable))
    # Current working dir, then source file dir
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

# Globals for audio capture
REC_SAMPLE_RATE = 24000
REC_NUM_CHANNELS = 1
REC_DTYPE = 'int16'


class AudioRecorder:
    def __init__(self, samplerate: int = REC_SAMPLE_RATE, channels: int = REC_NUM_CHANNELS):
        self.samplerate = samplerate
        self.channels = channels
        self._q: queue.Queue[np.ndarray] = queue.Queue()
        self._stream: sd.InputStream | None = None
        self._frames: List[np.ndarray] = []
        self._running = False

    def _callback(self, indata, frames, time_info, status):
        if status:
            pass
        self._q.put(indata.copy())

    def start(self):
        if self._running:
            return
        self._frames.clear()
        self._running = True
        self._stream = sd.InputStream(
            samplerate=self.samplerate,
            channels=self.channels,
            dtype=REC_DTYPE,
            callback=self._callback,
        )
        self._stream.start()
        threading.Thread(target=self._collector_thread, daemon=True).start()

    def _collector_thread(self):
        while self._running:
            try:
                chunk = self._q.get(timeout=0.1)
                self._frames.append(chunk)
            except queue.Empty:
                continue

    def stop(self) -> List[rtc.AudioFrame]:
        if not self._running:
            return []
        self._running = False
        try:
            if self._stream:
                self._stream.stop()
                self._stream.close()
        finally:
            self._stream = None

        if not self._frames:
            return []
        audio = np.concatenate(self._frames, axis=0)
        bstream = AudioByteStream(
            sample_rate=self.samplerate,
            num_channels=self.channels,
            samples_per_channel=self.samplerate // 20,
        )
        frames: List[rtc.AudioFrame] = []
        frames.extend(bstream.write(audio.tobytes()))
        frames.extend(bstream.flush())
        return frames


def stt_transcribe_audioframes(frames: List[rtc.AudioFrame]) -> str:
    stt = groq.STT(model='whisper-large-v3-turbo')
    ev = asyncio.run(stt.recognize(frames))
    if ev.alternatives:
        return ev.alternatives[0].text
    return ''


def llm_generate_reply(user_text: str) -> str:
    llm = groq.LLM(model='openai/gpt-oss-20b')
    chat = ChatContext()
    # ChatRole is a Literal alias, pass role as lowercase string
    chat.add_message(role="user", content=user_text)

    stream = llm.chat(chat_ctx=chat, tools=[], parallel_tool_calls=False)
    reply: list[str] = []

    async def _collect():
        async for chunk in stream:
            if chunk.delta and chunk.delta.content:
                reply.append(chunk.delta.content)
        await stream.close()

    asyncio.run(_collect())
    return ''.join(reply).strip()


def tts_speak(text: str):
    if not text:
        return
    tts = elevenlabs.TTS(voice_id=os.environ.get('ELEVEN_VOICE_ID', 'EXAVITQu4vr4xnSDxMaL'))
    stream = tts.synthesize(text)

    with sd.OutputStream(samplerate=tts.sample_rate, channels=1, dtype='int16') as out:
        async def _run():
            async for audio in stream:
                data = np.frombuffer(audio.frame.data, dtype=np.int16)
                out.write(data)

        asyncio.run(_run())


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title('VTC Playground')
        root.geometry('800x700')

        self.recorder = AudioRecorder()
        self.last_transcript = ''
        self.last_reply = ''
        self.tts_var = tk.BooleanVar(value=True)

        frm = ttk.Frame(root, padding=10)
        frm.pack(fill='both', expand=True)

        ttk.Label(frm, text='LiveKit-like Playground (Text + Voice)').pack(anchor='w')

        ttk.Label(frm, text='Input:').pack(anchor='w', pady=(8, 2))
        self.input_txt = scrolledtext.ScrolledText(frm, height=8)
        self.input_txt.pack(fill='both', expand=False)

        btn_row = ttk.Frame(frm)
        btn_row.pack(fill='x', pady=6)
        ttk.Button(btn_row, text='Speak', command=self.on_speak).pack(side='left')
        ttk.Button(btn_row, text='Stop', command=self.on_stop).pack(side='left', padx=(6, 0))
        ttk.Button(btn_row, text='Send', command=self.on_send).pack(side='left', padx=(6, 0))
        ttk.Checkbutton(btn_row, text='Speak reply (TTS)', variable=self.tts_var).pack(side='left', padx=(12, 0))

        ttk.Label(frm, text='Transcript:').pack(anchor='w', pady=(8, 2))
        self.transcript_txt = scrolledtext.ScrolledText(frm, height=6, state='normal')
        self.transcript_txt.pack(fill='both', expand=False)

        ttk.Label(frm, text='Reply:').pack(anchor='w', pady=(8, 2))
        self.reply_txt = scrolledtext.ScrolledText(frm, height=8, state='normal')
        self.reply_txt.pack(fill='both', expand=True)

        ttk.Button(frm, text='Exit', command=root.destroy).pack(anchor='e', pady=(8, 0))

    def set_transcript(self, text: str):
        self.transcript_txt.configure(state='normal')
        self.transcript_txt.delete('1.0', 'end')
        self.transcript_txt.insert('end', text)
        self.transcript_txt.configure(state='normal')

    def set_reply(self, text: str):
        self.reply_txt.configure(state='normal')
        self.reply_txt.delete('1.0', 'end')
        self.reply_txt.insert('end', text)
        self.reply_txt.configure(state='normal')

    def on_speak(self):
        try:
            self.recorder.start()
            self.set_transcript('Recording...')
        except Exception as e:
            messagebox.showerror('Error', f'Unable to start recording: {e}')

    def on_stop(self):
        frames = self.recorder.stop()
        if not frames:
            self.set_transcript('No audio captured.')
            return

        self.set_transcript('Transcribing...')

        def worker():
            try:
                self.last_transcript = stt_transcribe_audioframes(frames)
            except Exception as e:
                self.last_transcript = f'Error during STT: {e}'
            self.root.after(0, lambda: self.set_transcript(self.last_transcript))

        threading.Thread(target=worker, daemon=True).start()

    def on_send(self):
        user_text = self.input_txt.get('1.0', 'end').strip()
        if not user_text:
            user_text = self.last_transcript
        if not user_text:
            messagebox.showinfo('Info', 'Please enter text or record audio first.')
            return

        self.set_reply('Thinking...')

        def worker():
            try:
                self.last_reply = llm_generate_reply(user_text)
            except Exception as e:
                self.last_reply = f'Error during LLM generation: {e}'

            # update UI
            self.root.after(0, lambda: self.set_reply(self.last_reply))

            # optional TTS
            if self.tts_var.get() and self.last_reply and not self.last_reply.startswith('Error'):
                try:
                    tts_speak(self.last_reply)
                except Exception as e:
                    self.root.after(0, lambda: messagebox.showerror('TTS error', str(e)))

        threading.Thread(target=worker, daemon=True).start()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == '__main__':
    main()
